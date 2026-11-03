"""Numerical regressions independent of QGIS and GDAL (run directly with Python)."""
import ast
import importlib.util
from pathlib import Path
import unittest

import numpy as np
import scipy.ndimage as ndi

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cane_centers', ROOT / 'cane_centers.py')
centers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(centers)


class CenterFitTests(unittest.TestCase):
    def test_displaced_stool_with_outlier_and_missing_data(self):
        s = np.arange(0, 40.01, 0.25)
        truth = 0.06 * np.exp(-0.5 * ((s - 15) / 2.0) ** 2)
        observed = truth + np.random.default_rng(7).normal(0, 0.002, len(s))
        observed[90] = 0.60  # competing vegetation must not pull the line
        confidence = np.ones(len(s))
        confidence[(s > 23) & (s < 29)] = 0
        fit = centers.fit_center_offsets(s, observed, confidence, np.zeros(len(s)))
        self.assertLess(np.max(np.abs(fit)), 0.080001)
        self.assertLess(np.max(np.abs(np.diff(fit) / 0.25)), 0.030001)
        self.assertLess(np.max(np.abs(np.diff(fit, n=2) / 0.25 ** 2)), 0.020001)
        self.assertLess(abs(fit[60] - truth[60]), 0.025)
        self.assertLess(abs(fit[90]), 0.025)
        # No discontinuity at either side of missing observations.
        self.assertTrue(np.isfinite(fit).all())

    def test_no_observations_preserves_reference(self):
        s = np.arange(20, dtype=float) * 0.25
        baseline = 0.1 + s * 0.01
        fit = centers.fit_center_offsets(s, np.full(20, np.nan), np.zeros(20), baseline)
        np.testing.assert_array_equal(fit, baseline)

    def test_sampling_step_has_metric_meaning(self):
        fits = []
        for step in (0.125, 0.25, 0.5):
            s = np.arange(0, 30.01, step)
            truth = 0.05 * np.exp(-0.5 * ((s - 15) / 2) ** 2)
            fits.append(np.interp(np.arange(31), s, centers.fit_center_offsets(
                s, truth, np.ones(len(s)), np.zeros(len(s)))))
        self.assertLess(np.max(np.abs(fits[0] - fits[2])), 0.003)

    def test_plateau_has_one_candidate(self):
        score = np.zeros((30, 30), dtype=np.float32)
        score[12:15, 12:15] = 1
        r, c, cf = centers.local_maxima_centers(score, 0.03)
        self.assertEqual(len(r), 1)
        self.assertAlmostEqual(r[0], 13, delta=1)
        self.assertEqual(cf[0], 1)

    def test_rgb_core_rejects_bare_soil_and_nodata(self):
        yy, xx = np.mgrid[:100, :100]
        blob = (xx - 50) ** 2 + (yy - 50) ** 2 < 9 ** 2
        r = np.full((100, 100), 130, dtype=np.float32)
        g = np.full_like(r, 90)
        b = np.full_like(r, 60)
        r[blob], g[blob], b[blob] = 40, 150, 30
        valid = np.ones_like(blob)
        valid[:10] = False
        score, veg, _, _ = centers.stool_center_score(r, g, b, valid, 0.03)
        peak = np.unravel_index(np.argmax(score), score.shape)
        self.assertLess(np.hypot(peak[0] - 50, peak[1] - 50), 3)
        self.assertFalse(veg[:10].any())
        self.assertFalse(score[:10].any())

    def test_thin_leaning_leaf_does_not_move_compact_core(self):
        yy, xx = np.mgrid[:100, :100]
        core = (xx - 40) ** 2 + (yy - 50) ** 2 < 8 ** 2
        leaf = (np.abs(yy - 50) <= 1) & (xx >= 40) & (xx < 80)
        veg = core | leaf
        r = np.where(veg, 40, 130).astype(np.float32)
        g = np.where(veg, 150, 90).astype(np.float32)
        b = np.where(veg, 30, 60).astype(np.float32)
        score, _, _, _ = centers.stool_center_score(r, g, b, np.ones_like(veg), 0.03)
        row, col = np.unravel_index(np.argmax(score), score.shape)
        self.assertLess(np.hypot(row - 50, col - 40), 2)
        self.assertLess(abs(col - 40), abs(float(np.mean(np.nonzero(veg)[1])) - 40))

    def test_grid_centres_and_neighbouring_row(self):
        # Exercise the actual QGIS algorithm's numerical method without loading QGIS.
        tree = ast.parse((ROOT / 'RestituirLinhasAlgorithm.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                      and n.name == '_offsets_from_plant_centers')
        scope = {'np': np, 'ndi': ndi, 'fit_center_offsets': centers.fit_center_offsets}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<algorithm>', 'exec'), scope)
        step, resolution = 0.25, 0.10
        s = np.arange(0, 25.01, step)
        deltas = np.arange(-0.65, 0.66, 0.04)
        yy, xx = np.mgrid[:280, :40]
        # Array column 21 corresponds to map x=2.15 m: 0.15 m off reference x=2.
        signal = np.exp(-0.5 * ((xx - 21) / 1.1) ** 2) * np.ones_like(yy)
        signal += 2 * np.exp(-0.5 * ((xx - 36) / 1.1) ** 2)
        cols = np.broadcast_to((2 + deltas) / resolution - 0.5, (len(s), len(deltas)))
        rows = np.broadcast_to((s[:, None] + 1) / resolution - 0.5, cols.shape)
        r = np.floor(rows + 0.5).astype(int)
        c = np.floor(cols + 0.5).astype(int)
        offset, support = scope[method.name](None, signal, np.ones_like(signal, dtype=bool),
            r, c, rows, cols, deltas, 0.04, np.ones(len(deltas)), s, 1.5, True, 3.0, 2.0)
        self.assertTrue(support.any())
        self.assertAlmostEqual(float(np.median(offset)), 0.15, delta=0.012)


if __name__ == '__main__':
    unittest.main()
