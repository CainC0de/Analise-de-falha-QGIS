"""Estimate visible sugarcane clump cores from RGB; these are not measured stem bases.

Why not the canopy centroid?  Leaves droop/lean to one side and clumps differ in size,
so the green-mass centroid is dragged toward the leaning side.  This module combines
cues used in plant phenotyping for stem-emergence-point detection:

  1. Illumination-invariant vegetation (chromatic excess green), adaptive (Otsu) threshold.
  2. Morphological CORE: opening with a disk wider than a leaf removes thin drooping
     leaves; the distance transform of what remains peaks inside the dense clump core
     where many leaves overlap (inscribed-circle centre, medial-axis principle).
  3. Leaf CONVERGENCE voting: every leaf pixel votes along its leaf direction (structure
     tensor), pointing inward (toward higher vegetation density) — the rays of all the
     leaves of a clump intersect at its base, even when the clump leans to one side
     (generalised Hough / radial-symmetry transform).

The morphological core dominates the score; convergence is supporting evidence.
Occluded stem bases cannot be recovered with certainty from a nadir RGB image.
All coordinates use pixel CENTRES explicitly.
"""

import math
import os
import tempfile

import numpy as np
import scipy.ndimage as ndi


def row_context_support(s, occupied, aligned, min_run=3.0, window_m=8.0,
                        isolation_gap_m=1.5):
    """Conservative geometry support, not a botanical crop/weed classifier.

    Require sustained occupation and a narrow row signal. An island bracketed
    by long gaps cannot steer a row, even when its RGB core has high confidence.
    Returns trusted observations and regions locked to the reference geometry.
    """
    s = np.asarray(s, dtype=float)
    occupied = np.asarray(occupied, dtype=bool)
    aligned = np.asarray(aligned, dtype=bool)
    trusted = np.zeros(s.size, dtype=bool)
    if s.size < 2:
        return trusted, ~trusted
    h = float(np.median(np.diff(s)))
    win = max(3, int(round(window_m / h)) | 1)
    # Actual in-image window denominator: field ends are not assumed bare soil.
    den = ndi.uniform_filter1d(np.ones(s.size), win, mode='constant')
    coverage = ndi.uniform_filter1d(occupied.astype(float), win, mode='constant') / den
    rowness = ndi.uniform_filter1d((occupied & aligned).astype(float), win, mode='constant') / den
    contextual = (coverage >= 0.50) & (rowness >= 0.40)
    idx = np.flatnonzero(occupied)
    isolated = np.zeros(s.size, dtype=bool)
    spans = np.zeros(s.size, dtype=bool)
    groups = np.split(idx, np.flatnonzero(np.diff(s[idx]) > 0.75) + 1)
    groups = [g for g in groups if g.size]
    for i, group in enumerate(groups):
        a, b = int(group[0]), int(group[-1])
        left_gap = s[a] - (s[groups[i - 1][-1]] if i else s[0])
        right_gap = (s[groups[i + 1][0]] if i + 1 < len(groups) else s[-1]) - s[b]
        # At field/image ends require a full window of observed bare ground;
        # ordinary headland margins must not invalidate an otherwise sound row.
        left_required = isolation_gap_m if i else max(window_m, isolation_gap_m)
        right_required = isolation_gap_m if i + 1 < len(groups) else max(window_m, isolation_gap_m)
        surrounded = left_gap >= left_required and right_gap >= right_required
        if surrounded:
            isolated[a:b + 1] = True
        elif s[b] - s[a] >= min_run:
            spans[a:b + 1] = True
    trusted = occupied & aligned & spans & contextual & ~isolated
    # Sustained low support is protected, including a scattered succession of
    # apparently strong cores. Short normal inter-plant gaps remain interpolable.
    low = ~contextual
    labels, _ = ndi.label(low)
    protected = isolated.copy()
    for extent in ndi.find_objects(labels):
        if extent and (extent[0].stop - extent[0].start) * h >= max(2.0, min_run):
            protected[extent[0]] = True
    if not np.any(trusted):
        protected[:] = True
    trusted[protected] = False
    return trusted, protected


def fit_center_offsets(s, observed, confidence, baseline, max_flex=0.08,
                       max_slope=0.03, max_curvature=0.02, fixed_zero=None):
    """Robust penalized fit with explicit limits on lateral flexion and its derivatives.

    Missing observations have zero weight. They are interpolated continuously;
    never cut the fitted correction with a vegetation mask after fitting.
    Limits refer to the correction relative to baseline (metres, m/m, and 1/m).
    With fixed_zero, protected vertices are eliminated exactly, the corridor
    opens toward the reference, and derivative limits apply to the total offset.
    """
    from scipy import sparse
    from scipy.sparse.linalg import factorized

    s, observed, confidence, baseline = [np.asarray(a, dtype=np.float64)
                                        for a in (s, observed, confidence, baseline)]
    if not (s.shape == observed.shape == confidence.shape == baseline.shape):
        raise ValueError('Centre fit arrays must have the same shape.')
    n = s.size
    if n < 3:
        return baseline.copy()
    if not np.all(np.isfinite(s)) or not np.all(np.isfinite(baseline)):
        raise ValueError('Distances and baseline must be finite.')
    steps = np.diff(s)
    if np.any(steps <= 0) or not np.allclose(steps, np.median(steps), rtol=0.02):
        raise ValueError('Centre fit requires uniformly spaced increasing distances.')
    h = float(np.median(steps))
    weight = np.where(np.isfinite(observed) & np.isfinite(confidence),
                      np.clip(confidence, 0.0, 1.0), 0.0)
    locked = None if fixed_zero is None else np.asarray(fixed_zero, dtype=bool)
    if locked is not None:
        if locked.shape != s.shape:
            raise ValueError('Reference lock mask must match the distance array.')
        weight[locked] = 0.0
    if not np.any(weight):
        return baseline.copy() if locked is None else np.zeros(n)
    target = np.where(weight > 0, observed - baseline, 0.0)
    eye = sparse.eye(n, format='csc')
    d1 = sparse.diags([-np.ones(n - 1), np.ones(n - 1)], [0, 1],
                      shape=(n - 1, n), format='csc') / h
    d2 = sparse.diags([np.ones(n - 2), -2 * np.ones(n - 2), np.ones(n - 2)],
                      [0, 1, 2], shape=(n - 2, n), format='csc') / (h * h)
    constraint = sparse.vstack([eye, d1, d2], format='csc')
    limits = np.r_[np.full(n, max_flex), np.full(n - 1, max_slope),
                   np.full(n - 2, max_curvature)]
    if np.any(limits <= 0):
        raise ValueError('Flexion limits must be positive.')
    lower, upper = -limits.copy(), limits.copy()
    if locked is not None:
        # Include the reference (zero offset) in the feasible corridor, so the
        # entire transition can return to the project instead of just +/-8 cm.
        lower[:n] = np.minimum(lower[:n], -baseline)
        upper[:n] = np.maximum(upper[:n], -baseline)
        lower[np.flatnonzero(locked)] = -baseline[locked]
        upper[np.flatnonzero(locked)] = -baseline[locked]
        # Derivative bounds now apply to the TOTAL offset, including baseline.
        reference_derivatives = constraint @ baseline
        lower[n:] -= reference_derivatives[n:]
        upper[n:] -= reference_derivatives[n:]
    # Whittaker penalty, in metric units so results do not depend on sample step.
    penalty = 0.02 * eye + 0.10 * (d1.T @ d1) + 0.30 * (d2.T @ d2)
    rho = 0.5
    gram = rho * (constraint.T @ constraint)
    z = np.zeros(constraint.shape[0])
    dual = z.copy()
    flex = np.zeros(n)
    robust = weight.copy()
    for _ in range(3):
        matrix = sparse.diags(robust, format='csc') + penalty + gram
        if locked is None:
            solve = factorized(matrix)
        else:
            # Eliminate locked unknowns exactly. Merely penalizing their offset
            # leaves tiny boundary errors that become kinks after zeroing.
            free = ~locked
            fixed = np.where(locked, -baseline, 0.0)
            boundary_rhs = np.asarray(matrix @ fixed)[free]
            solve_free = factorized(matrix[free][:, free].tocsc())
            def solve(rhs):
                answer = fixed.copy()
                answer[free] = solve_free(rhs[free] - boundary_rhs)
                return answer
        for iteration in range(180 if locked is None else 1200):
            flex = solve(robust * target + rho * (constraint.T @ (z - dual)))
            values = constraint @ flex
            previous = z
            z = np.clip(values + dual, lower, upper)
            dual += values - z
            if iteration > 20 and max(np.max(np.abs(values - z)),
                                       np.max(np.abs(z - previous))) < 1e-6:
                break
        residual = np.abs(target - flex)
        robust = weight * np.minimum(1.0, 0.06 / np.maximum(residual, 1e-9))
    # Feasibility safeguard if ADMM reaches its iteration budget. Scaling keeps
    # continuity and all three bounds simultaneously, unlike sequential clipping.
    if locked is None:
        ratio = float(np.max(np.abs(constraint @ flex) / limits))
        if ratio > 1.0:
            flex /= ratio
        return baseline + flex
    result = np.clip(baseline + flex, baseline + lower[:n], baseline + upper[:n])
    result[locked] = 0.0
    ratio = max(1.0, float(np.max(np.abs(d1 @ result))) / max_slope,
                float(np.max(np.abs(d2 @ result))) / max_curvature)
    # Scaling toward zero preserves the lock and the convex feasible corridor.
    return result / ratio


def chromatic_exg(r, g, b):
    r = r.astype(np.float32)
    g = g.astype(np.float32)
    b = b.astype(np.float32)
    s = r + g + b + 1e-3
    return (2.0 * g - r - b) / s


def _otsu(values, bins=128):
    if values.size < 100:
        return float(np.median(values)) if values.size else 0.0
    lo, hi = np.percentile(values, [1, 99])
    if hi - lo < 1e-6:
        return float(lo)
    hist, edges = np.histogram(np.clip(values, lo, hi), bins=bins, range=(lo, hi))
    hist = hist.astype(np.float64)
    centers = 0.5 * (edges[:-1] + edges[1:])
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers)
    mt = m0[-1]
    with np.errstate(divide='ignore', invalid='ignore'):
        mu0 = m0 / w0
        mu1 = (mt - m0) / w1
        between = w0 * w1 * (mu0 - mu1) ** 2
    between[~np.isfinite(between)] = 0.0
    return float(centers[int(np.argmax(between))])


def _disk(radius_px):
    r = max(1, int(round(radius_px)))
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (x * x + y * y) <= r * r


def stool_center_score(r, g, b, valid, px, core_radius_m=0.07, vote_len_m=0.40,
                       veg_threshold=None, use_votes=True):
    """Return (score, veg_mask, core_edt, votes) for one RGB window of pixel size px (m)."""
    exg = chromatic_exg(r, g, b)
    exg = np.where(valid, exg, -1.0)
    exg_s = ndi.gaussian_filter(exg, 0.7)
    thr = veg_threshold
    if thr is None:
        vv = exg_s[valid]
        thr = max(0.02, _otsu(vv)) if vv.size else 0.05
    veg = valid & (exg_s > thr)
    veg = ndi.binary_opening(veg, structure=np.ones((2, 2), dtype=bool))

    # 2) morphological core (thin drooping leaves removed)
    core = ndi.binary_opening(veg, structure=_disk(core_radius_m / px))
    edt = ndi.distance_transform_edt(core).astype(np.float32) * px
    edt = ndi.gaussian_filter(edt, max(0.8, 0.02 / px))
    density = ndi.gaussian_filter(veg.astype(np.float32), 0.10 / px)

    votes = None
    if use_votes:
        # 3) leaf convergence voting (structure tensor orientation, inward rays)
        gy = ndi.sobel(exg_s, axis=0)
        gx = ndi.sobel(exg_s, axis=1)
        sig = max(1.0, 0.04 / px)
        jxx = ndi.gaussian_filter(gx * gx, sig)
        jyy = ndi.gaussian_filter(gy * gy, sig)
        jxy = ndi.gaussian_filter(gx * gy, sig)
        tr = jxx + jyy + 1e-9
        coh = np.sqrt((jxx - jyy) ** 2 + 4.0 * jxy ** 2) / tr
        # leaf direction = eigenvector of the SMALLEST eigenvalue (along the leaf)
        theta = 0.5 * np.arctan2(2.0 * jxy, jxx - jyy) + 0.5 * np.pi
        ux = np.cos(theta)
        uy = np.sin(theta)            # image coords: x = col, y = row
        # inward sign: toward higher broad vegetation density
        dens_big = ndi.gaussian_filter(veg.astype(np.float32), 0.15 / px)
        dgy = ndi.sobel(dens_big, axis=0)
        dgx = ndi.sobel(dens_big, axis=1)
        sgn = np.sign(ux * dgx + uy * dgy)
        sgn[sgn == 0] = 1.0
        ux *= sgn
        uy *= sgn
        sel = veg & (coh > 0.25)
        rows, cols = np.nonzero(sel)
        h, w = veg.shape
        acc = np.zeros(h * w, dtype=np.float64)
        if rows.size:
            wv = coh[rows, cols].astype(np.float64)
            dxs = ux[rows, cols]
            dys = uy[rows, cols]
            step = max(1.0, 0.03 / px)
            n_steps = max(2, int(vote_len_m / (step * px)))
            for k in range(1, n_steps + 1):
                rr = np.rint(rows + dys * step * k).astype(np.int64)
                cc = np.rint(cols + dxs * step * k).astype(np.int64)
                ok = (rr >= 0) & (rr < h) & (cc >= 0) & (cc < w)
                acc += np.bincount(rr[ok] * w + cc[ok], weights=wv[ok], minlength=h * w)
        votes = ndi.gaussian_filter(acc.reshape(h, w).astype(np.float32), max(1.0, 0.04 / px))

    def _n(a):
        hi = float(np.percentile(a[veg], 98)) if np.any(veg) else 0.0
        return np.clip(a / hi, 0.0, 1.0) if hi > 1e-9 else np.zeros_like(a)

    core_n = _n(edt)
    # Votes alone can form rings around rounded clumps. The inscribed core must
    # dominate, otherwise even a symmetric plant can be displaced toward its edge.
    score = core_n ** 1.5 * (0.75 + 0.25 * _n(density))
    if not np.any(core):
        score = 0.30 * _n(density)
    if votes is not None:
        score = score * (0.75 + 0.25 * _n(votes))
    score = np.where(veg | core, score, 0.0).astype(np.float32)
    return score, veg, edt, votes


def local_maxima_centers(score, px, min_dist_m=0.18, min_score=0.10):
    size = max(3, int(round(2 * min_dist_m / px)) | 1)
    mx = ndi.maximum_filter(score, size=size)
    peaks = (score >= mx) & (score > min_score)
    # One representative per connected maximum plateau, including flat cores.
    labels, count = ndi.label(peaks)
    positions = ndi.maximum_position(score, labels, range(1, count + 1)) if count else []
    rows = np.asarray([p[0] for p in positions], dtype=int)
    cols = np.asarray([p[1] for p in positions], dtype=int)
    if rows.size == 0:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    # sub-pixel refinement: weighted centroid in a small (~6 cm) neighbourhood
    rad = max(1, int(round(0.06 / px)))
    h, w = score.shape
    rr_off, cc_off = np.mgrid[-rad:rad + 1, -rad:rad + 1]
    out_r = np.empty(rows.size)
    out_c = np.empty(rows.size)
    for i, (r0, c0) in enumerate(zip(rows, cols)):
        r1 = np.clip(r0 + rr_off, 0, h - 1)
        c1 = np.clip(c0 + cc_off, 0, w - 1)
        wv = score[r1, c1]
        sw = float(wv.sum()) + 1e-9
        out_r[i] = float((wv * r1).sum()) / sw
        out_c[i] = float((wv * c1).sum()) / sw
    return out_r, out_c, score[rows, cols].astype(np.float64)


def detect_stool_centers(raster_source, dst_wkt, xmin, ymin, xmax, ymax, feedback=None,
                         max_res=0.045, tile_m=40.0, halo_m=0.8, use_votes=True,
                         core_radius_m=0.07, keep_fn=None,
                         progress_start=0.0, progress_span=30.0):
    """Detect stool centres over a map extent.  Returns (x, y, confidence) arrays in dst CRS.

    keep_fn(x, y) -> bool array can be given to discard centres far from planned rows.
    """
    from osgeo import gdal

    src = gdal.Open(raster_source, gdal.GA_ReadOnly)
    if src is None:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    band_count = src.RasterCount
    if band_count < 3:
        if feedback is not None:
            feedback.pushInfo('Imagem sem RGB: centros estimados pela nuvem e pela grade de cultura.')
        return np.zeros(0), np.zeros(0), np.zeros(0)
    metric = gdal.AutoCreateWarpedVRT(src, None, dst_wkt)
    if metric is None:
        raise ValueError('Não foi possível estimar a resolução métrica do RGB.')
    gt = metric.GetGeoTransform()
    native = max(math.hypot(gt[1], gt[4]), math.hypot(gt[2], gt[5]))
    metric = None
    src = None
    # Never invent resolution by upsampling a coarse orthomosaic.
    res = max(0.005, max_res, native)
    halo_m = max(halo_m, 3 * res)
    xs_all, ys_all, cf_all = [], [], []
    nx = max(1, int(math.ceil((xmax - xmin) / tile_m)))
    ny = max(1, int(math.ceil((ymax - ymin) / tile_m)))
    total = nx * ny
    done = 0
    with tempfile.TemporaryDirectory(prefix='cane_centers_') as tmp:
        for iy in range(ny):
            for ix in range(nx):
                if feedback is not None and feedback.isCanceled():
                    return np.zeros(0), np.zeros(0), np.zeros(0)
                tx0 = xmin + ix * tile_m
                ty0 = ymin + iy * tile_m
                tx1 = min(xmax, tx0 + tile_m)
                ty1 = min(ymax, ty0 + tile_m)
                bx0, by0, bx1, by1 = tx0 - halo_m, ty0 - halo_m, tx1 + halo_m, ty1 + halo_m
                w = max(8, int(round((bx1 - bx0) / res)))
                h = max(8, int(round((by1 - by0) / res)))
                vrt = os.path.join(tmp, 't.vrt')
                ds = gdal.Warp(vrt, raster_source, options=gdal.WarpOptions(
                    format='VRT', outputBounds=(bx0, by0, bx0 + w * res, by0 + h * res),
                    width=w, height=h, resampleAlg='bilinear', dstSRS=dst_wkt))
                if ds is None:
                    raise RuntimeError('Não foi possível ler um bloco RGB reprojetado.')
                ds = None
                ds = gdal.Open(vrt)
                if ds is None or band_count < 3:
                    done += 1
                    continue
                r = ds.GetRasterBand(1).ReadAsArray()
                g = ds.GetRasterBand(2).ReadAsArray()
                b = ds.GetRasterBand(3).ReadAsArray()
                valid = np.isfinite(r) & np.isfinite(g) & np.isfinite(b)
                valid &= (r > 0) | (g > 0) | (b > 0)
                for band_i in (1, 2, 3):
                    valid &= ds.GetRasterBand(band_i).GetMaskBand().ReadAsArray() > 0
                ds = None
                done += 1
                if feedback is not None:
                    feedback.setProgress(progress_start + progress_span * done / total)
                if valid.mean() < 0.02:
                    continue
                score, veg, _, _ = stool_center_score(r, g, b, valid, res,
                                                      core_radius_m=core_radius_m,
                                                      use_votes=use_votes)
                rr, cc, cf = local_maxima_centers(score, res)
                if rr.size == 0:
                    continue
                X = bx0 + (cc + 0.5) * res        # pixel CENTRE convention
                Y = by0 + h * res - (rr + 0.5) * res
                inside = (X >= tx0) & (X < tx1) & (Y >= ty0) & (Y < ty1)
                X, Y, cf = X[inside], Y[inside], cf[inside]
                if keep_fn is not None and X.size:
                    k = keep_fn(X, Y)
                    X, Y, cf = X[k], Y[k], cf[k]
                xs_all.append(X)
                ys_all.append(Y)
                cf_all.append(cf)
    if not xs_all:
        return np.zeros(0), np.zeros(0), np.zeros(0)
    return np.concatenate(xs_all), np.concatenate(ys_all), np.concatenate(cf_all)
