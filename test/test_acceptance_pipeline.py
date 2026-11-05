"""Full production-pipeline regressions with independently generated geometry."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('acceptance_pipeline_helper',ROOT/'scripts/validate_acceptance_qgis.py')
acceptance=importlib.util.module_from_spec(spec);spec.loader.exec_module(acceptance)

class PipelineAcceptanceTests(unittest.TestCase):
    def test_automatic_trace_recovers_every_observed_row_despite_grid_phase(self):
        with tempfile.TemporaryDirectory() as temp:
            report=acceptance.run_case('automatic',temp)
            self.assertIsNone(report['error'],report.get('traceback'))
            # All four observed rows plus the bracketed, regularly spaced
            # missing row must be recovered. The inference remains explicit.
            self.assertEqual(report['assigned_parts_per_row'],[1]*5)
            self.assertEqual(report['origins'].get('inferida_entre_vizinhas'),1)
            self.assertTrue(all(report['gates'].values()),report['gates'])
            self.assertEqual(report['invalid_rows'],0)
            self.assertEqual(report['crossing_pairs'],0)
            self.assertEqual(report['unmatched_predictions'],0)

    def test_automatic_trace_on_completely_planted_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            report=acceptance.run_case('automatic_healthy',temp)
            self.assertIsNone(report['error'],report.get('traceback'))
            self.assertEqual(report['assigned_parts_per_row'],[1]*5)
            self.assertEqual(report['detected_gaps'],0)
            self.assertGreaterEqual(min(report['row_coverage_within_10cm']),.95)

    def test_previously_rejected_cases_keep_original_acceptance_limits(self):
        for case in ('straight_shifted','contour','oblique','automatic_oblique','automatic_contour'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                report=acceptance.run_case(case,temp)
                self.assertIsNone(report['error'],report.get('traceback'))
                self.assertTrue(all(report['gates'].values()),report['gates'])

