"""Planting-gap measurement independent of line reconstruction.

State 1 is vegetation, 0 supported absence, -1 unavailable, -2 ambiguous.
These observations cannot certify stalk presence beneath a closed canopy.
"""
import math
import os
from collections import OrderedDict
import numpy as np
import scipy.ndimage as ndi


def intervals_from_states(edges, states, minimum_m, min_crop_m=0.0):
    """Measure absent intervals by cell edges, never by neighbouring crop vertices."""
    edges = np.asarray(edges, dtype=float)
    states = np.asarray(states, dtype=np.int8).copy()
    if len(edges) != len(states) + 1 or np.any(np.diff(edges) <= 0):
        raise ValueError('Invalid sampling intervals.')
    if not np.isfinite(minimum_m) or minimum_m <= 0:
        raise ValueError('Minimum gap length must be positive.')
    if not len(states):
        return [], 0.0
    # Small isolated green responses cannot split an otherwise continuous gap.
    # Retain genuine end plants and never convert unknown pixels to bare soil.
    changes = np.r_[0, np.flatnonzero(np.diff(states) != 0) + 1, len(states)]
    for a, b in zip(changes[:-1], changes[1:]):
        if (states[a] == 1 and edges[b] - edges[a] < min_crop_m
                and a > 0 and b < len(states) and states[a-1] == 0 and states[b] == 0):
            states[a:b] = 0
    changes = np.r_[0, np.flatnonzero(np.diff(states) != 0) + 1, len(states)]
    gaps = []
    for a, b in zip(changes[:-1], changes[1:]):
        if states[a] != 0 or edges[b] - edges[a] + 1e-9 < minimum_m:
            continue
        kind = 'total' if a == 0 and b == len(states) else ('inicial' if a == 0 else 'final' if b == len(states) else 'interna')
        if (a > 0 and states[a-1] == -1) or (b < len(states) and states[b] == -1):
            kind = 'limite_dados'
        elif (a > 0 and states[a-1] == -2) or (b < len(states) and states[b] == -2):
            kind = 'limite_incerto'
        gaps.append((float(edges[a]), float(edges[b]), kind))
    unknown = float(np.diff(edges)[states < 0].sum())
    return gaps, unknown


def local_positive_quantile(values, step, quantile=.8, window_m=1.0):
    """Centred physical-window quantile, ignoring absent object samples.

    A component's distant wide canopy cannot redefine a narrow stool's width.
    Sorting small fixed windows avoids per-station Python percentile callbacks.
    """
    radius=max(1,int(math.ceil(window_m/(2*step))))
    windows=np.lib.stride_tricks.sliding_window_view(
        np.pad(np.asarray(values,dtype=float),(radius,radius)),2*radius+1)
    count=(windows>0).sum(axis=1);ordered=np.sort(windows,axis=1)
    rank=np.maximum(count-1,0)*quantile
    first=ordered.shape[1]-np.maximum(count,1)
    lo=first+np.floor(rank).astype(int);hi=first+np.ceil(rank).astype(int)
    ar=np.arange(len(values));fraction=rank-np.floor(rank)
    return ordered[ar,lo]*(1-fraction)+ordered[ar,hi]*fraction


def _metric_disk(radius, along_step, cross_step):
    y=np.arange(-int(math.ceil(radius/along_step)),int(math.ceil(radius/along_step))+1)*along_step
    x=np.arange(-int(math.ceil(radius/cross_step)),int(math.ceil(radius/cross_step))+1)*cross_step
    return y[:,None]**2+x[None,:]**2<=radius**2+1e-12


def visible_soil_support(crop, vegetation, labels, valid, seed, soil, offsets,
                         spacing, longitudinal_step, diagnostics=None):
    """Visible axial soil can overrule peripheral leaves, never a plant body.

    Geometry and metric minimum are unchanged. Compact off-axis plants and
    central seeds veto recovery. This is not inference beneath a closed canopy.
    """
    cross_step=float(np.median(np.diff(offsets)))
    recovered=np.zeros(len(crop),dtype=bool)
    if longitudinal_step>.06 or cross_step>.06:return recovered
    inner=np.abs(offsets)<=min(.35,.28*spacing)
    central=np.abs(offsets)<=min(.10,.09*spacing)
    seed_axis=np.abs(offsets)<=min(.04,.04*spacing)
    known=valid[:,central].sum(axis=1)>=max(2,int(math.ceil(.90*central.sum())))
    soil_fraction=(soil[:,central]&valid[:,central]).sum(axis=1)/np.maximum(1,valid[:,central].sum(axis=1))
    # Soil dominance already vetoes a centrally occupied plant. A single
    # central leaf pixel must not veto the entire interval on its own.
    axis_plant=(seed[:,central]&valid[:,central]).sum(axis=1)>(.25*central.sum())
    candidate=crop&known&(soil_fraction>=.80)&~axis_plant
    if diagnostics is not None:
        diagnostics.update(soil_fraction=soil_fraction,axis_plant=axis_plant,
                           body_present=np.zeros(len(crop),bool),candidate=candidate)
    if not candidate.any():return recovered
    radius=max(.055,longitudinal_step,cross_step)
    element=_metric_disk(radius,longitudinal_step,cross_step)
    closing=_metric_disk(.035,longitudinal_step,cross_step)
    py,px=element.shape[0]//2+1,element.shape[1]//2+1
    material=vegetation&~soil
    padded=np.pad(material,((py,py),(px,px)),mode='edge')
    closed=ndi.binary_closing(padded,structure=closing)
    distance=ndi.distance_transform_edt(closed,sampling=(longitudinal_step,cross_step))
    peak_window=(max(3,int(math.ceil(.5/longitudinal_step))|1),
                 max(3,int(math.ceil(.3/cross_step))|1))
    peaks=ndi.maximum_filter(distance,size=peak_window,mode='nearest')
    core=((distance>=radius)&(distance>=.75*peaks))[py:-py,px:-px]
    core &= inner[None,:]
    body=ndi.binary_dilation(core,structure=element)&valid
    body_present=body[:,inner].any(axis=1)
    # A small isolated stool can be below the opening diameter. Preserve
    # compact objects even off-axis, while rejecting long thin leaf fragments.
    for obj in np.unique(labels[material&candidate[:,None]]):
        rr,cc=np.nonzero(material&(labels==obj))
        if not len(rr):continue
        height=(rr.max()-rr.min()+1)*longitudinal_step
        width=(cc.max()-cc.min()+1)*cross_step
        area=len(rr)*longitudinal_step*cross_step
        compact=(max(height,width)<=4*min(height,width) and area>=.01
                 and area>=.35*height*width
                 and abs(float(np.mean(offsets[cc])))<=min(.35,.28*spacing))
        if compact:
            centre=float(np.median(rr));reach=max(.05,min(.10,.20*height))/longitudinal_step
            body_present[np.abs(np.arange(len(crop))-centre)<=reach]=True
    if diagnostics is not None:diagnostics['body_present']=body_present
    # Recover bounded visible intervals between actual plant bodies. A long
    # skinny green row/weed stripe is not reinterpreted as a total planting gap.
    visible=known&(soil_fraction>=.80)&~axis_plant&~body_present
    limits=np.r_[0,np.flatnonzero(np.diff(visible.astype(int)))+1,len(visible)]
    look=max(1,int(math.ceil(.30/longitudinal_step)))
    for a,b in zip(limits[:-1],limits[1:]):
        if (not visible[a] or (b-a)*longitudinal_step>min(3.,2*spacing)
                or not body_present[max(0,a-look):a].any()
                or not body_present[b:min(len(visible),b+look)].any()):continue
        recovered[a:b]=candidate[a:b]
    return recovered


def classify_cross_sections(r, g, b, valid, offsets, spacing, longitudinal_step=0.05,
                            refine_visible=True, return_evidence=False):
    """Compare canopy chromaticity with local inter-row background, not G>=R.

    Darkness or weak plant evidence is ambiguity, never proof of bare soil.
    Longitudinal observations are not dilated or filled over detected plants.
    """
    # Promote before arithmetic: uint8 band arrays otherwise wrap at 255.
    r, g, b = [np.asarray(v,dtype=float) for v in (r,g,b)]
    offsets = np.asarray(offsets,dtype=float)
    cross_step = float(np.median(np.diff(offsets)))
    inner = np.abs(offsets) <= min(0.35, 0.28 * spacing)
    flank = np.abs(offsets) >= 0.35 * spacing
    total = r + g + b + 1e-9
    exg = (2*g-r-b)/total
    ngrdi = (g-r)/(g+r+1e-9)
    valid = (np.asarray(valid,dtype=bool) & np.isfinite(total)
             & (r>=0) & (g>=0) & (b>=0) & (total>1e-6))
    def background(values):
        data = np.where(valid[:,flank], values[:,flank], np.nan)
        # Avoid all-NaN median warnings while retaining missing-background flags.
        data = np.ma.masked_invalid(data)
        med = np.ma.median(data,axis=1).filled(np.nan)
        return med[:,None]
    bg_exg, bg_ngrdi, bg_light = [background(v) for v in (exg,ngrdi,total)]
    de, dn = exg-bg_exg, ngrdi-bg_ngrdi
    # RGBVI and blue chromaticity retain evidence in yellow-green leaves even
    # when R exceeds G. Local contrast, not yellowness alone, separates this
    # evidence from the soil/straw surrounding the same cross section.
    rgbvi = (g*g-r*b)/(g*g+r*b+1e-9)
    blue = b/total
    dv = rgbvi-background(rgbvi)
    db = background(blue)-blue
    absolute = (exg > 0.10) & (ngrdi > 0.025) & (g > b)
    relative = ((exg > 0.08) & (ngrdi > -0.02) & (de > 0.045)
                & (dn > 0.015) & (g > 1.04*b) & (total < 0.85*bg_light))
    olive = ((exg > 0.045) & (ngrdi > -0.075) & (de > 0.022)
             & (dn > 0.003) & (g > 1.04*b) & (total < 0.78*bg_light))
    yellow = ((exg>0.08) & (ngrdi>-.06) & (rgbvi>0.18)
              & (dv>0.08) & (db>0.025) & (dn>-.015) & (g>1.18*b))
    # Stronger chlorosis can overlap dry residue in RGB. Expose coherent
    # objects as uncertain rather than asserting either crop or absence.
    chlorotic = ((exg>0.04) & (ngrdi>-.16) & (rgbvi>0.10)
                 & (dv>0.06) & (db>0.025) & (g>1.12*b)) & valid
    seed = (absolute | relative | olive | yellow) & valid
    weak = ((((de > 0.012) & (dn > 0) & (g>b) & (exg>0.02) & (ngrdi>-.085))
             | absolute | chlorotic) & valid)
    # Hysteresis/connected objects: weak straw colour variations cannot on
    # their own confirm plants or split an otherwise empty planting row.
    pixel_area = longitudinal_step * cross_step
    labels, count = ndi.label(weak, structure=np.ones((3,3),dtype=bool))
    areas = np.bincount(labels.ravel(), minlength=count+1) * pixel_area
    # Attribute evidence to THIS row: strong colour in the outer flanks may
    # belong to another clump. It cannot confirm a weak leaf/tail entering
    # the corridor unless there is also a seed inside the evaluated corridor.
    row_seed = seed & inner[None,:]
    seeded = np.bincount(labels[row_seed], minlength=count+1)*pixel_area >= 0.003
    accepted = seeded & (areas >= 0.01)
    accepted[0] = False
    # Bound hysteresis growth: a cane seed must not flood a connected carpet
    # of straw that happens to be greener than reddish inter-row soil.
    distance = (ndi.distance_transform_edt(~row_seed, sampling=(longitudinal_step,cross_step))
                if row_seed.any() else np.full(seed.shape,np.inf))
    vegetation = accepted[labels] & (distance <= 0.20)
    # One peripheral leaf/sample must not erase a 50 cm gap. Require a
    # contiguous transverse support of 6 cm (or one native coarse sample),
    # rather than adding unrelated specks across the full corridor. Off-axis
    # clumps inside the corridor still count; the geometry is never moved.
    crop=np.zeros(len(r),dtype=bool);core_objects=np.zeros(count+1,dtype=bool)
    columns=np.arange(inner.sum())[None,:]
    for obj in np.unique(labels[vegetation]):
        mask=vegetation[:,inner]&(labels[:,inner]==obj)
        last_empty=np.maximum.accumulate(np.where(~mask,columns,-1),axis=1)
        runs=np.where(mask,columns-last_empty,0).max(axis=1)*cross_step
        present=runs>0
        if not present.any():continue
        # A partially sampled outer edge is not the middle of this object.
        # Scale to each object, so genuinely small isolated stools still count.
        typical=local_positive_quantile(runs,longitudinal_step)
        width=np.maximum(min(.06,.04*spacing),np.minimum(.15,.5*typical))
        supported=runs+1e-9>=width
        crop|=supported;core_objects[obj]=supported.any()
    # Only spatially coherent ambiguity interrupts absence. A single weak
    # colour pixel no longer resets the minimum-gap counter every few cm.
    ambiguous_pixels = ((weak & (total < 0.90*bg_light)) | chlorotic) & ~vegetation
    ambiguous_labels, n_ambiguous = ndi.label(ambiguous_pixels, structure=np.ones((3,3),dtype=bool))
    ambiguous_areas = np.bincount(ambiguous_labels.ravel(), minlength=n_ambiguous+1)*pixel_area
    ambiguous = ambiguous_areas >= 0.025
    ambiguous[0] = False
    periphery=vegetation&core_objects[labels]&~crop[:,None]
    dark = (total < 0.65*bg_light) & valid & ~periphery
    dark_labels, dark_count = ndi.label(dark, structure=np.ones((3,3),dtype=bool))
    dark_areas = np.bincount(dark_labels.ravel(), minlength=dark_count+1) * pixel_area
    dark_objects = dark_areas >= 0.01
    dark_objects[0] = False
    unsure = (ambiguous[ambiguous_labels] | dark_objects[dark_labels])[:,inner].any(axis=1)
    known = valid[:,inner].sum(axis=1) >= max(2,int(np.ceil(inner.sum()*0.75)))
    background_known = valid[:,flank].sum(axis=1) >= 2
    baseline=np.where(~known,-1,np.where(crop,1,np.where(
        unsure | ~background_known,-2,0))).astype(np.int8)
    soil=(valid&~seed&~chlorotic&(total>.70*bg_light)
          &(((de<.035)&(dn<.015))|((rgbvi<.09)&(ngrdi<.01))))
    details={}
    eligible=(baseline==1)|(baseline==-2)
    recovered=visible_soil_support(eligible,vegetation,labels,valid,seed,soil,
        offsets,spacing,longitudinal_step,diagnostics=details if return_evidence else None) if refine_visible else np.zeros(len(crop),bool)
    states=baseline.copy();states[recovered&(baseline!=-1)]=0
    if return_evidence:return states,dict(baseline=baseline,recovered=recovered,soil=soil,**details)
    return states


def sample_polyline(xy, step):
    if not np.isfinite(step) or step <= 0:
        raise ValueError('Sampling step must be positive.')
    xy = np.asarray(xy, dtype=float)
    lengths = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    xy = np.vstack([xy[0], xy[1:][lengths > 1e-8]])
    if len(xy) < 2:
        raise ValueError('Line has no measurable length.')
    s = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    # Keep full nominal steps. Redistributing the remainder via linspace makes
    # ten nominal 5 cm cells slightly shorter than 50 cm and rejects the limit.
    edges = np.arange(int(math.floor(s[-1] / step)) + 1,dtype=float)*step
    if s[-1]-edges[-1] > 1e-9:
        edges = np.r_[edges,s[-1]]
    else:
        edges[-1] = s[-1]
    stations = (edges[:-1] + edges[1:]) / 2
    segment = np.minimum(np.searchsorted(s, stations, side='right') - 1, len(xy)-2)
    tangent = xy[segment+1] - xy[segment]
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    centres = np.column_stack([np.interp(stations, s, xy[:,i]) for i in (0,1)])
    normals = np.column_stack([-tangent[:,1], tangent[:,0]])
    return edges, centres, normals


def review_intervals(edges, states):
    """Expose unassessed intervals separately, without relabelling them gaps."""
    edges=np.asarray(edges);states=np.asarray(states)
    limits=np.r_[0,np.flatnonzero(np.diff(states)!=0)+1,len(states)]
    return [(float(edges[a]),float(edges[b]),'sem_dados' if states[a]==-1 else 'incerto')
            for a,b in zip(limits[:-1],limits[1:]) if b>a and states[a]<0]


def segment_coordinates(xy, start, end):
    xy = np.asarray(xy, dtype=float)
    s = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    a = [np.interp(start,s,xy[:,i]) for i in (0,1)]
    b = [np.interp(end,s,xy[:,i]) for i in (0,1)]
    return np.vstack([a, xy[(s > start) & (s < end)], b])


class GapRasterSampler:
    """Bounded-window reads of an undilated RGB/classified raster in a metric CRS."""
    def __init__(self, source, target_wkt, directory, refine_visible=True):
        from osgeo import gdal
        src = gdal.Open(source)
        if src is None:
            raise ValueError('Não foi possível abrir a imagem para medir falhas.')
        self.rgb = src.RasterCount >= 3
        self.refine_visible=refine_visible
        # Honour RGB colour metadata (e.g. a TIFF physically stored as B,G,R).
        # Unlabelled RGB inputs retain the documented first-three-band order.
        colours = {src.GetRasterBand(i).GetColorInterpretation():i
                   for i in range(1,src.RasterCount+1)}
        self.rgb_bands = tuple(colours.get(colour,default) for colour,default in
            ((gdal.GCI_RedBand,1),(gdal.GCI_GreenBand,2),(gdal.GCI_BlueBand,3)))
        projected = gdal.AutoCreateWarpedVRT(src, None, target_wkt)
        if projected is None:
            raise ValueError('Não foi possível preparar a imagem para medir falhas.')
        gt = projected.GetGeoTransform()
        self.res = max(0.01, math.hypot(gt[1],gt[4]), math.hypot(gt[2],gt[5]))
        projected = None
        self.ds = gdal.Warp(os.path.join(directory,'gap_measurement.vrt'), src,
            format='VRT', dstSRS=target_wkt, xRes=self.res, yRes=self.res,
            resampleAlg='bilinear' if self.rgb else 'near', dstAlpha=True)
        src = None
        if self.ds is None:
            raise ValueError('Não foi possível criar a grade de medição de falhas.')
        self.gt = self.ds.GetGeoTransform()
        self._tiles=OrderedDict();self._tile_bytes=0

    def _native_sample(self, xy, bands):
        """Gather only native tiles touched by the corridor, bounded to 32 MiB.

        Reading a diagonal strip as its rectangular bounding box fetches mostly
        unused pixels. Cache raw tiles and convert only the sampled colours.
        """
        shape=np.shape(xy)[:-1];points=np.asarray(xy).reshape(-1,2)
        cols=np.floor((points[:,0]-self.gt[0])/self.gt[1]).astype(np.int64)
        rows=np.floor((points[:,1]-self.gt[3])/self.gt[5]).astype(np.int64)
        inside=(cols>=0)&(rows>=0)&(cols<self.ds.RasterXSize)&(rows<self.ds.RasterYSize)
        result=np.zeros((len(bands),len(points)),dtype=float)
        selected=np.flatnonzero(inside)
        if not len(selected):return result.reshape((len(bands),)+shape),inside.reshape(shape)
        ncols=int(math.ceil(self.ds.RasterXSize/256))
        keys=(rows[selected]//256)*ncols+cols[selected]//256
        unique,inverse=np.unique(keys,return_inverse=True)
        for number,key in enumerate(unique):
            by,bx=divmod(int(key),ncols);cache_key=(tuple(bands),bx,by)
            tile=self._tiles.pop(cache_key,None)
            if tile is None:
                x0,y0=bx*256,by*256
                tile=self.ds.ReadAsArray(x0,y0,min(256,self.ds.RasterXSize-x0),
                    min(256,self.ds.RasterYSize-y0),band_list=list(bands))
                if tile.ndim==2:tile=tile[None,:,:]
                self._tile_bytes+=tile.nbytes
            self._tiles[cache_key]=tile
            while self._tile_bytes>32*1024*1024 and len(self._tiles)>1:
                _,removed=self._tiles.popitem(last=False);self._tile_bytes-=removed.nbytes
            indices=selected[inverse==number]
            result[:,indices]=tile[:,rows[indices]-by*256,cols[indices]-bx*256]
        return result.reshape((len(bands),)+shape),inside.reshape(shape)

    def valid_points(self, xy):
        """Native pixel-footprint validity; no interpolation across mask holes."""
        values,inside=self._native_sample(xy,[self.ds.RasterCount])
        return inside&np.isfinite(values[0])&(values[0]>0)

    def states(self, centres, normals, spacing, feedback):
        # A narrow cross section tolerates small lateral errors without borrowing
        # vegetation from adjacent rows. No longitudinal maximum filter is used.
        half = 0.45 * spacing
        # N intervals need N+1 samples; the old count could leave a transverse
        # step larger than a native pixel and miss a narrow stool entirely.
        offsets = np.linspace(-half, half, max(15,(int(math.ceil(2*half/self.res))+1) | 1))
        states = np.full(len(centres), -1, dtype=np.int8)
        self.last_refined=np.zeros(len(centres),dtype=bool)
        self.last_baseline=states.copy()
        self.last_soil_fraction=np.zeros(len(centres));self.last_axis_plant=np.zeros(len(centres),bool)
        self.last_body_present=np.zeros(len(centres),bool)
        along_step = float(np.median(np.linalg.norm(np.diff(centres,axis=0),axis=1))) if len(centres)>1 else self.res
        cross_step=float(np.median(np.diff(offsets)))
        # Cover local width, bounded growth and the longest one-cell component
        # needed to reach the 0.025 m² ambiguity-area threshold.
        halo_m=max(1.0,.025/cross_step+along_step,
                    min(3.,2*spacing)+.5 if self.refine_visible and self.rgb else 0.)
        halo = max(2,int(math.ceil(halo_m/max(along_step,1e-6))))
        batch=512 if self.refine_visible and self.rgb else 256
        for start in range(0, len(centres), batch):
            if feedback.isCanceled():
                return states
            stop = min(start+batch, len(centres))
            read_start, read_stop = max(0,start-halo), min(len(centres),stop+halo)
            selection = slice(start-read_start,stop-read_start)
            xy = centres[read_start:read_stop,None,:] + normals[read_start:read_stop,None,:] * offsets[None,:,None]
            bands=self.rgb_bands+(self.ds.RasterCount,) if self.rgb else (1,self.ds.RasterCount)
            values,inside=self._native_sample(xy,bands)
            alpha=values[-1];valid=inside&np.isfinite(alpha)&(alpha>0)
            if self.rgb:
                # Keep native observations for metric boundaries. Bilinear
                # mixing followed by weak-colour growth can expand a canopy
                # into bare pixels and erase a minimum-size gap.
                r,g,b=values[:3]
                classified,evidence=classify_cross_sections(r,g,b,valid,offsets,spacing,along_step,
                    refine_visible=self.refine_visible,return_evidence=True)
                states[start:stop]=classified[selection]
                self.last_baseline[start:stop]=evidence['baseline'][selection]
                self.last_refined[start:stop]=evidence['recovered'][selection]
                if 'soil_fraction' in evidence:
                    self.last_soil_fraction[start:stop]=evidence['soil_fraction'][selection]
                    self.last_axis_plant[start:stop]=evidence['axis_plant'][selection]
                    self.last_body_present[start:stop]=evidence['body_present'][selection]
                continue
            else:
                classified=values[0]
                valid &= np.isin(classified,[0,1])
                green=classified==1
            inner=np.abs(offsets)<=min(.35,.28*spacing)
            known=valid[:,inner].sum(axis=1)>=max(2,int(np.ceil(inner.sum()*.75)))
            evidence=(green & valid)[:,inner]
            crop=evidence.any(axis=1)
            states[start:stop]=np.where(known,np.where(crop,1,0),-1)[selection]
            self.last_baseline[start:stop]=states[start:stop]
        return states

    def close(self):
        self.ds = None
        self._tiles.clear();self._tile_bytes=0
