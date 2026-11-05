"""Planting-gap measurement independent of line reconstruction.

State 1 is vegetation, 0 supported absence, -1 unavailable, -2 ambiguous.
These observations cannot certify stalk presence beneath a closed canopy.
"""
import math
import os
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


def classify_cross_sections(r, g, b, valid, offsets, spacing, longitudinal_step=0.05):
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
        width=max(min(.06,.04*spacing),min(.15,.5*float(np.quantile(runs[present],.8))))
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
    return np.where(~known,-1,np.where(crop,1,np.where(
        unsure | ~background_known,-2,0))).astype(np.int8)


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
    def __init__(self, source, target_wkt, directory):
        from osgeo import gdal
        src = gdal.Open(source)
        if src is None:
            raise ValueError('Não foi possível abrir a imagem para medir falhas.')
        self.rgb = src.RasterCount >= 3
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

    def valid_points(self, xy):
        """Native pixel-footprint validity; no interpolation across mask holes."""
        xy=np.asarray(xy,dtype=float);result=np.zeros(len(xy),dtype=bool)
        cols=np.floor((xy[:,0]-self.gt[0])/self.gt[1]).astype(np.int64)
        rows=np.floor((xy[:,1]-self.gt[3])/self.gt[5]).astype(np.int64)
        inside=(cols>=0)&(rows>=0)&(cols<self.ds.RasterXSize)&(rows<self.ds.RasterYSize)
        indices=np.flatnonzero(inside)
        # Bucket by native tiles: bounded reads, even for a long diagonal line.
        buckets={}
        for i in indices:buckets.setdefault((int(cols[i]//256),int(rows[i]//256)),[]).append(i)
        band=self.ds.GetRasterBand(self.ds.RasterCount)
        for (bx,by),idx in buckets.items():
            x0,y0=bx*256,by*256
            data=band.ReadAsArray(x0,y0,min(256,self.ds.RasterXSize-x0),min(256,self.ds.RasterYSize-y0))
            result[idx]=data[rows[idx]-y0,cols[idx]-x0]>0
        return result

    def states(self, centres, normals, spacing, feedback):
        # A narrow cross section tolerates small lateral errors without borrowing
        # vegetation from adjacent rows. No longitudinal maximum filter is used.
        half = 0.45 * spacing
        offsets = np.linspace(-half, half, max(15,int(math.ceil(2*half/self.res)) | 1))
        states = np.full(len(centres), -1, dtype=np.int8)
        along_step = float(np.median(np.linalg.norm(np.diff(centres,axis=0),axis=1))) if len(centres)>1 else self.res
        halo = max(2,int(math.ceil(0.5/max(along_step,1e-6))))
        for start in range(0, len(centres), 256):
            if feedback.isCanceled():
                return states
            stop = min(start+256, len(centres))
            read_start, read_stop = max(0,start-halo), min(len(centres),stop+halo)
            selection = slice(start-read_start,stop-read_start)
            xy = centres[read_start:read_stop,None,:] + normals[read_start:read_stop,None,:] * offsets[None,:,None]
            cols = (xy[:,:,0] - self.gt[0]) / self.gt[1] - .5
            rows = (xy[:,:,1] - self.gt[3]) / self.gt[5] - .5
            x0=max(0,int(np.floor(cols.min()))-1); y0=max(0,int(np.floor(rows.min()))-1)
            x1=min(self.ds.RasterXSize,int(np.ceil(cols.max()))+2)
            y1=min(self.ds.RasterYSize,int(np.ceil(rows.max()))+2)
            if x1<=x0 or y1<=y0:
                continue
            coordinates=[rows-y0,cols-x0]
            def read(band, order=1):
                data=band.ReadAsArray(x0,y0,x1-x0,y1-y0)
                return ndi.map_coordinates(data.astype(float),coordinates,order=order,mode='nearest')
            alpha=read(self.ds.GetRasterBand(self.ds.RasterCount),order=0)
            valid=(np.isfinite(alpha) & (alpha>0) & (cols>=-.5) & (rows>=-.5)
                   & (cols<self.ds.RasterXSize-.5) & (rows<self.ds.RasterYSize-.5))
            if self.rgb:
                # Keep native observations for metric boundaries. Bilinear
                # mixing followed by weak-colour growth can expand a canopy
                # into bare pixels and erase a minimum-size gap.
                r,g,b=[read(self.ds.GetRasterBand(i),order=0) for i in self.rgb_bands]
                states[start:stop] = classify_cross_sections(r,g,b,valid,offsets,spacing,along_step)[selection]
                continue
            else:
                values=read(self.ds.GetRasterBand(1),order=0)
                valid &= np.isin(values,[0,1])
                green=values==1
            inner=np.abs(offsets)<=min(.35,.28*spacing)
            known=valid[:,inner].sum(axis=1)>=max(2,int(np.ceil(inner.sum()*.75)))
            evidence=(green & valid)[:,inner]
            crop=evidence.any(axis=1)
            states[start:stop]=np.where(known,np.where(crop,1,0),-1)[selection]
        return states

    def close(self):
        self.ds = None
