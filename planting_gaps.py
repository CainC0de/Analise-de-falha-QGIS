"""Planting-gap measurement independent of line reconstruction.

State 1 is visible green vegetation, 0 absence, -1 unavailable imagery.
These observations cannot certify stalk presence beneath a closed canopy.
"""
import math
import os
import numpy as np
import scipy.ndimage as ndi


def intervals_from_states(edges, states, minimum_m, min_crop_m=0.10):
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
        gaps.append((float(edges[a]), float(edges[b]), kind))
    unknown = float(np.diff(edges)[states == -1].sum())
    return gaps, unknown


def sample_polyline(xy, step):
    xy = np.asarray(xy, dtype=float)
    lengths = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    xy = np.vstack([xy[0], xy[1:][lengths > 1e-8]])
    if len(xy) < 2:
        raise ValueError('Line has no measurable length.')
    s = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    edges = np.linspace(0., s[-1], max(1, int(math.ceil(s[-1] / step))) + 1)
    stations = (edges[:-1] + edges[1:]) / 2
    segment = np.minimum(np.searchsorted(s, stations, side='right') - 1, len(xy)-2)
    tangent = xy[segment+1] - xy[segment]
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    centres = np.column_stack([np.interp(stations, s, xy[:,i]) for i in (0,1)])
    normals = np.column_stack([-tangent[:,1], tangent[:,0]])
    return edges, centres, normals


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

    def states(self, centres, normals, spacing, feedback):
        # A narrow cross section tolerates small lateral errors without borrowing
        # vegetation from adjacent rows. No longitudinal maximum filter is used.
        half = min(0.20, 0.18 * spacing)
        offsets = np.linspace(-half, half, 7)
        states = np.full(len(centres), -1, dtype=np.int8)
        for start in range(0, len(centres), 256):
            if feedback.isCanceled():
                return states
            stop = min(start+256, len(centres))
            xy = centres[start:stop,None,:] + normals[start:stop,None,:] * offsets[None,:,None]
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
                return ndi.map_coordinates(data.astype(float),coordinates,order=order,mode='constant',cval=np.nan)
            alpha=read(self.ds.GetRasterBand(self.ds.RasterCount))
            valid=np.isfinite(alpha) & (alpha>0)
            if self.rgb:
                r,g,b=[read(self.ds.GetRasterBand(i)) for i in (1,2,3)]
                gli=(2*g-r-b)/(2*g+r+b+1e-6)
                ngrdi=(g-r)/(g+r+1e-6)
                green=(gli>0.035)&(ngrdi>-.025)&(g>b)&(g>=.97*r)
                valid &= np.isfinite(r+g+b)
            else:
                values=read(self.ds.GetRasterBand(1),order=0)
                valid &= np.isin(values,[0,1])
                green=values==1
            known=valid.sum(axis=1)>=5
            # Two independent cross-section samples, including a central sample,
            # reject isolated lateral leaves/speckles in the search corridor.
            crop=((green & valid).sum(axis=1)>=2) & (green[:,2:5]&valid[:,2:5]).any(axis=1)
            states[start:stop]=np.where(known,np.where(crop,1,0),-1)
        return states

    def close(self):
        self.ds = None
