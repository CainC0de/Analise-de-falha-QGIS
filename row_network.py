"""Constrained geometric completion; inferred geometry is not observed crop.

Only interpolate missing INTERIOR rows between parallel, regularly spaced
observations. Never extrapolate new rows beyond the outside observed rows.
"""
import numpy as np
import scipy.ndimage as ndi
from scipy.spatial import cKDTree
from .planting_gaps import segment_coordinates


def stationing(xy):
    xy=np.asarray(xy,dtype=float)
    return np.r_[0.,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]


def clip_native(parts, sampler, feedback):
    clipped=[];owners=[];step=max(.01,min(.025,sampler.res/2))
    for owner,part in enumerate(parts):
        if feedback.isCanceled():return [],[]
        xy=np.asarray(part,dtype=float);s=stationing(xy)
        if s[-1]<2.5:continue
        stations=np.linspace(0,s[-1],int(np.ceil(s[-1]/step))+1)
        points=np.column_stack([np.interp(stations,s,xy[:,i]) for i in (0,1)])
        valid=sampler.valid_points(points)
        changes=np.r_[0,np.flatnonzero(np.diff(valid.astype(int)))+1,len(valid)]
        for a,b in zip(changes[:-1],changes[1:]):
            if not valid[a] or stations[b-1]-stations[a]<2.5:continue
            start,end=stations[a],stations[b-1]
            # Locate transition inside the adjacent native mask cells.
            for edge in ('start','end'):
                idx=a if edge=='start' else b-1
                other=idx-1 if edge=='start' else idx+1
                if other<0 or other>=len(stations):continue
                good,bad=stations[idx],stations[other]
                for _ in range(8):
                    mid=(good+bad)/2
                    point=np.array([[np.interp(mid,s,xy[:,i]) for i in (0,1)]])
                    if sampler.valid_points(point)[0]:good=mid
                    else:bad=mid
                if edge=='start':start=good
                else:end=good
            clipped.append(segment_coordinates(xy,start,end));owners.append(owner)
    return clipped,owners


def connect_observed_fragments(parts, spacing, feedback, support=None, max_bridge=60.):
    """Join same-lane fragments only between two independently observed guides.

    The inserted geometry carries zero plant support. Endpoint direction alone
    is insufficient: guides must span the gap, bracket the lane, have regular
    offsets and agree at both fragment ends. No guide-free extrapolation.
    """
    lines=[np.asarray(p,dtype=float) for p in parts]
    weights=[np.asarray(w,dtype=bool) for w in support] if support is not None else [np.zeros(len(p),bool) for p in lines]
    if len(lines)<4:return lines,weights,['observada']*len(lines)
    ends=np.array([point for p in lines for point in (p[0],p[-1])])
    midpoints=np.array([p[len(p)//2] for p in lines]);guide_tree=cKDTree(midpoints)
    candidates=[]
    for ei,ej in cKDTree(ends).query_pairs(max_bridge):
        if feedback.isCanceled():return lines,weights,['observada']*len(lines)
        i,si=divmod(ei,2);j,sj=divmod(ej,2)
        if i==j:continue
        pa=lines[i] if si else lines[i][::-1]
        pb=lines[j] if not sj else lines[j][::-1]
        sa=stationing(pa);sb=stationing(pb)
        ia=max(0,int(np.searchsorted(sa,max(0.,sa[-1]-2.))))
        ib=min(len(pb)-1,max(1,int(np.searchsorted(sb,min(2.,sb[-1])))))
        ta=pa[-1]-pa[ia];tb=pb[ib]-pb[0]
        ta/=max(1e-9,np.linalg.norm(ta));tb/=max(1e-9,np.linalg.norm(tb))
        if ta@tb<.97:continue
        tangent=ta+tb;tangent/=np.linalg.norm(tangent);normal=np.array([-tangent[1],tangent[0]])
        origin=pa[-1];delta=pb[0]-origin;length=float(delta@tangent);lateral=float(delta@normal)
        # This is only a broad search bound. A contour can turn inside a long
        # gap even when both endpoint tangents agree. The spanning guides below
        # must still establish the same planting lane at both ends.
        if length<max(.5,.4*spacing) or abs(lateral)>max(.25*spacing,.25*length):continue
        _,near=guide_tree.query((pa[-1]+pb[0])/2,k=min(24,len(lines)))
        grid=np.linspace(0.,length,max(3,int(np.ceil(length/.10))+1))
        guides=[];duplicate=False
        for k in np.atleast_1d(near):
            k=int(k)
            if k in (i,j):continue
            p=lines[k];w=weights[k];u=(p-origin)@tangent;v=(p-origin)@normal
            if u[-1]<u[0]:u,v,w=u[::-1],v[::-1],w[::-1]
            if np.any(np.diff(u)<=1e-6) or u[0]>-.5 or u[-1]<length+.5:continue
            a=float(np.interp(0.,u,v));b=float(np.interp(length,u,v)-lateral)
            if abs(a)<.35*spacing and abs(b)<.35*spacing:duplicate=True;break
            if a*b<=0 or abs(a-b)>.20*spacing:continue
            offset=(a+b)/2;count=round(abs(offset)/spacing)
            if count<1 or count>3 or abs(abs(offset)-count*spacing)>.18*spacing:continue
            observed=np.interp(grid,u,w.astype(float))>.5
            if observed.mean()<.60 or not observed[grid<=.5].any() or not observed[grid>=length-.5].any():continue
            guides.append((offset,np.interp(grid,u,v)))
        if duplicate:continue
        left=[g for g in guides if g[0]<0];right=[g for g in guides if g[0]>0]
        if not left or not right:continue
        left=max(left,key=lambda g:g[0]);right=min(right,key=lambda g:g[0])
        separation=right[1]-left[1]
        if np.max(np.abs(separation-np.median(separation)))>.20*spacing:continue
        fraction=-left[0]/(right[0]-left[0]);values=left[1]+fraction*separation
        residual=np.array([values[0],values[-1]-lateral])
        if np.max(np.abs(residual))>.15*spacing:continue
        values-=np.linspace(residual[0],residual[1],len(grid))
        bridge=origin+grid[:,None]*tangent+values[:,None]*normal
        candidates.append((length,i,si,j,sj,bridge))
    # A fragment has at most one connection at each end, and no cycles.
    parent=list(range(len(lines)));connections={}
    def find(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for _,i,si,j,sj,bridge in sorted(candidates,key=lambda item:item[0]):
        if (i,si) in connections or (j,sj) in connections or find(i)==find(j):continue
        parent[find(j)]=find(i)
        connections[i,si]=(j,sj,bridge);connections[j,sj]=(i,si,bridge[::-1])
    groups={}
    for i in range(len(lines)):groups.setdefault(find(i),[]).append(i)
    joined=[];joined_weights=[];origins=[]
    for group in sorted(groups.values(),key=min):
        start=next((i,side) for i in group for side in (0,1) if (i,side) not in connections)
        i,incoming=start;pieces=[];evidence=[]
        while True:
            p,w=(lines[i],weights[i]) if incoming==0 else (lines[i][::-1],weights[i][::-1])
            pieces.append(p);evidence.append(w)
            link=connections.get((i,1-incoming))
            if link is None:break
            i,incoming,bridge=link
            pieces.append(bridge[1:-1]);evidence.append(np.zeros(max(0,len(bridge)-2),bool))
        joined.append(np.concatenate(pieces));joined_weights.append(np.concatenate(evidence))
        origins.append('observada_conectada' if len(group)>1 else 'observada')
    return joined,joined_weights,origins


def complete_network(parts, spacing, sampler, feedback, max_extension=4.5, support=None, initial_origins=None):
    """Complete locally parallel families without letting another field veto all."""
    lines=[np.asarray(p,dtype=float) for p in parts]
    if len(lines)<2:return lines,initial_origins or ['observada']*len(lines)
    chords=np.array([p[-1]-p[0] for p in lines]);chords/=np.linalg.norm(chords,axis=1)[:,None]
    groups=[]
    for i,chord in enumerate(chords):
        for group in groups:
            # Complete-link orientation groups prevent a chain of gradual
            # direction changes from combining incompatible field families.
            if all(abs(chord@chords[j])>=.985 for j in group):group.append(i);break
        else:groups.append([i])
    completed=list(lines);origins=list(initial_origins or ['observada']*len(lines));extra=[];extra_origins=[]
    for group in groups:
        if feedback.isCanceled():return [],[]
        local,local_origins=_complete_parallel_network([lines[i] for i in group],spacing,sampler,feedback,
            max_extension,[support[i] for i in group] if support is not None else None)
        for j,i in enumerate(group):completed[i]=local[j]
        extra.extend(local[len(group):]);extra_origins.extend(local_origins[len(group):])
    # Local orientation families may overlap spatially. Check inferred rows
    # against ALL completed observations, including other direction families.
    dense=[]
    for p in completed:
        s=stationing(p);grid=np.linspace(0.,s[-1],max(2,int(np.ceil(s[-1]/.20))+1))
        dense.append(np.column_stack([np.interp(grid,s,p[:,d]) for d in (0,1)]))
    tree=cKDTree(np.concatenate(dense));kept=[];kept_origins=[];kept_trees=[]
    for candidate,kind in zip(extra,extra_origins):
        probe=candidate[::2]
        if np.min(tree.query(probe)[0])<.30*spacing:continue
        if any(np.min(other.query(probe)[0])<.30*spacing for other in kept_trees):continue
        kept.append(candidate);kept_origins.append(kind);kept_trees.append(cKDTree(probe))
    return completed+kept,origins+kept_origins


def _complete_parallel_network(parts, spacing, sampler, feedback, max_extension=4.5, support=None):
    """Extend to shared observed headlands and interpolate bracketed rows."""
    lines=[np.asarray(p,dtype=float) for p in parts]
    if len(lines)<2:return lines,['observada']*len(lines)
    chords=np.array([p[-1]-p[0] for p in lines]);chords/=np.linalg.norm(chords,axis=1)[:,None]
    base=chords[0];chords*=np.where(chords@base<0,-1.,1.)[:,None]
    tangent=np.median(chords,axis=0);tangent/=np.linalg.norm(tangent)
    normal=np.array([-tangent[1],tangent[0]]);origin=np.mean([p[0] for p in lines],axis=0)
    profiles=[]
    for p in lines:
        u=(p-origin)@tangent;v=(p-origin)@normal
        if u[-1]<u[0]:u,v=u[::-1],v[::-1]
        # Multiple orientations / hairpins cannot share a one-dimensional model.
        if np.any(np.diff(u)<=1e-6):return lines,['observada']*len(lines)
        profiles.append((u,v))
    # Do not let a different field or terrace orient this network.
    if np.min(chords@tangent)<.98:return lines,['observada']*len(lines)
    margin=max(.6,2*sampler.res) # account for the coarse 60 cm tracing march
    left=float(np.quantile([u[0] for u,v in profiles],.15))-margin
    right=float(np.quantile([u[-1] for u,v in profiles],.85))+margin
    model=None;model_offsets=None
    if support is not None and len(profiles)>=3:
        weights=[]
        for p,w in zip(lines,support):
            weights.append(np.asarray(w,dtype=float) if ((p[-1]-p[0])@tangent)>0 else np.asarray(w,dtype=float)[::-1])
        anchor=int(np.argmax([np.sum(w) for w in weights]));au,av=profiles[anchor]
        offsets=[];regular=True
        for (u,v),w in zip(profiles,weights):
            use=(w>.5)&(u>=au[0])&(u<=au[-1])&(np.interp(u,au,weights[anchor])>.5)
            if use.sum()<10:regular=False;break
            offset=float(np.median(v[use]-np.interp(u[use],au,av)))
            if abs(offset-round(offset/spacing)*spacing)>.10*spacing:regular=False;break
            offsets.append(offset)
        if regular:
            grid=np.arange(left,right+.05,.05);observations=[]
            for (u,v),w,offset in zip(profiles,weights,offsets):
                ok=(grid>=u[0])&(grid<=u[-1])&(np.interp(grid,u,w)>.5)
                observations.append(np.where(ok,np.interp(grid,u,v)-offset,np.nan))
            values=np.ma.masked_invalid(np.asarray(observations));shape=np.ma.median(values,axis=0).filled(np.nan)
            good=(values.count(axis=0)>=2)&np.isfinite(shape)
            if good.mean()>.60:
                model=(grid,np.interp(grid,grid[good],shape[good]));model_offsets=offsets
                # Preserve the consensus end curvature when extending to the mask.
                for side in (0,1):
                    edge=grid[good][0 if side==0 else -1]
                    select=good&(abs(grid-edge)<=2.)
                    outside=grid<edge if side==0 else grid>edge
                    if select.sum()>=3:
                        model[1][outside]=np.polyval(np.polyfit(grid[select]-edge,shape[select],2),grid[outside]-edge)
    completed=[]
    for index,(u,v) in enumerate(profiles):
        if feedback.isCanceled():return [],[]
        lo=max(left,u[0]-max_extension);hi=min(right,u[-1]+max_extension)
        # Two unsupported fragments on the same lane must not extrapolate
        # through each other. A verified two-guide connection happens earlier;
        # otherwise reserve a separate half of the intervening interval for
        # each end, rather than inventing overlapping observations.
        for j,(other_u,other_v) in enumerate(profiles):
            if j==index:continue
            if 0.<other_u[0]-u[-1]<2*max_extension and abs(other_v[0]-v[-1])<.35*spacing:
                hi=min(hi,(u[-1]+other_u[0])/2-.025)
            if 0.<u[0]-other_u[-1]<2*max_extension and abs(v[0]-other_v[-1])<.35*spacing:
                lo=max(lo,(u[0]+other_u[-1])/2+.025)
        grid=np.linspace(lo,hi,max(2,int(np.ceil((hi-lo)/.05))+1))
        values=np.interp(grid,u,v)
        for side in (0,1):
            select=(u<=u[0]+4.) if side==0 else (u>=u[-1]-4.)
            edge=u[0] if side==0 else u[-1];outside=grid<u[0] if side==0 else grid>u[-1]
            if select.sum()>=3:
                # Quadratic extrapolation magnifies a few centimetres of end
                # noise into metres over a 4.5 m headland extension. Use the
                # observed end trend; curvature still comes from a supported
                # shared model when that independent model is available.
                coef=np.polyfit(u[select]-edge,v[select],1)
                values[outside]=np.polyval(coef,grid[outside]-edge)
        if model is not None:
            target=np.interp(grid,model[0],model[1])+model_offsets[index]
            known=np.interp(grid,u,weights[index],left=0,right=0)
            blend=ndi.gaussian_filter1d((known<.5).astype(float),sigma=.20/max(.01,np.median(np.diff(grid))))
            values+=blend*np.clip(target-values,-.30*spacing,.30*spacing)
        completed.append(origin+grid[:,None]*tangent+values[:,None]*normal)
    origins=['observada']*len(completed);new=[];new_trees=[]
    existing_tree=cKDTree(np.concatenate([p[::2] for p in completed]))
    # Neighbour search is bounded; a large field need not compare every pair.
    middle=np.array([p[len(p)//2] for p in completed]);tree=cKDTree(middle)
    pairs=set()
    for i,p in enumerate(middle):
        _,neighbours=tree.query(p,k=min(9,len(middle)))
        pairs.update(tuple(sorted((i,int(j)))) for j in np.atleast_1d(neighbours) if i!=j)
    for i,j in sorted(pairs):
        ui,vi=profiles[i];uj,vj=profiles[j]
        lo,hi=max(ui[0],uj[0]),min(ui[-1],uj[-1])
        if hi-lo<max(6.,.6*min(ui[-1]-ui[0],uj[-1]-uj[0])):continue
        grid=np.linspace(lo,hi,max(3,int((hi-lo)/.25)+1))
        a,b=np.interp(grid,ui,vi),np.interp(grid,uj,vj);delta=b-a
        distance=float(np.median(delta));count=int(round(abs(distance)/spacing))
        if count<2 or count>4 or abs(abs(distance)-count*spacing)>.12*spacing:continue
        if np.max(np.abs(delta-distance))>.12*spacing:continue
        for k in range(1,count):
            vv=a+delta*k/count;xy=origin+grid[:,None]*tangent+vv[:,None]*normal
            # Existing/interpolated observations between this pair block duplicates.
            probe=xy[::max(1,len(xy)//30)]
            if np.median(existing_tree.query(probe)[0])<.35*spacing:continue
            if any(np.median(tree.query(probe)[0])<.35*spacing for tree in new_trees):continue
            # Use the completed neighbours, including common headland extension.
            pa,pb=completed[i],completed[j]
            ua=(pa-origin)@tangent;ub=(pb-origin)@tangent
            common=np.linspace(max(ua[0],ub[0]),min(ua[-1],ub[-1]),max(len(pa),len(pb)))
            aa=np.column_stack([np.interp(common,ua,pa[:,d]) for d in (0,1)])
            bb=np.column_stack([np.interp(common,ub,pb[:,d]) for d in (0,1)])
            inferred=aa+(bb-aa)*k/count
            if model is not None:
                target=np.interp(common,model[0],model[1])+model_offsets[i]+(model_offsets[j]-model_offsets[i])*k/count
                inferred=origin+common[:,None]*tangent+target[:,None]*normal
            # A median-distance veto misses a short existing fragment on the
            # inferred lane. Check the entire path at <=10 cm sampling.
            if np.min(existing_tree.query(inferred[::2])[0])<.30*spacing:continue
            if any(np.min(tree.query(inferred[::2])[0])<.30*spacing for tree in new_trees):continue
            new.append(inferred)
            new_trees.append(cKDTree(inferred[::2]))
    return completed+new,origins+['inferida_entre_vizinhas']*len(new)


def register_empty_rows(polylines, references, provenance, spacing):
    """Transfer a coherent field-wide normal registration to unsupported rows.

    Requires >=3 independently supported reference rows, small residuals and
    small displacement. A green island on one row cannot move another row.
    """
    if len(references)<3:return polylines,provenance
    # A valid straight project often has just two vertices. Densify before
    # computing local normals; indexing neighbours of two endpoints yields a
    # zero tangent and can make the registration solve singular/NaN.
    dense=[]
    for reference in references:
        ref=np.asarray(reference,dtype=float);s=stationing(ref)
        grid=np.linspace(0,s[-1],max(3,int(np.ceil(s[-1]/.25))+1))
        dense.append(np.column_stack([np.interp(grid,s,ref[:,i]) for i in (0,1)]))
    references=dense
    trees=[cKDTree(np.asarray(p)) for p in references]
    normals=[];offsets=[];owners=set()
    for item in polylines:
        if item[6]<35. or item[2]<6.:continue
        xy=np.array([(p.x(),p.y()) for p in item[0]])
        probe=xy[::max(1,len(xy)//40)]
        distances=[np.median(tree.query(probe)[0]) for tree in trees];owner=int(np.argmin(distances))
        ref=np.asarray(references[owner]);_,idx=trees[owner].query(probe)
        idx=np.clip(idx,1,len(ref)-2);t=ref[idx+1]-ref[idx-1];t/=np.linalg.norm(t,axis=1)[:,None]
        n=np.column_stack([-t[:,1],t[:,0]]);d=np.sum((probe-ref[idx])*n,axis=1)
        keep=np.abs(d)<.25*spacing
        if keep.sum()<5:continue
        normals.extend(n[keep]);offsets.extend(d[keep]);owners.add(owner)
    if len(owners)<3:return polylines,provenance
    n=np.asarray(normals);d=np.asarray(offsets);shift=np.linalg.lstsq(n,d,rcond=.05)[0]
    residual=np.abs(n@shift-d)
    if np.percentile(residual,80)>.04 or np.linalg.norm(shift)>.20*spacing:return polylines,provenance
    if np.linalg.norm(shift)<.02:return polylines,provenance
    from qgis.core import QgsPointXY
    result=[];provenance=list(provenance)
    for i,item in enumerate(polylines):
        if item[6]<10.:
            value=list(item);value[0]=[QgsPointXY(p.x()+shift[0],p.y()+shift[1]) for p in item[0]]
            result.append(tuple(value));provenance[i]='projeto_registrado'
        else:result.append(item)
    return result,provenance
