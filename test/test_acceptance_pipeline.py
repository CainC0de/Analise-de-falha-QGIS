"""Full production-pipeline regressions with independently generated geometry."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('acceptance_pipeline_helper',ROOT/'scripts/validate_acceptance_qgis.py')
acceptance=importlib.util.module_from_spec(spec);spec.loader.exec_module(acceptance)

class PipelineAcceptanceTests(unittest.TestCase):
    def test_automatic_large_absence_keeps_a_complete_row(self):
        for case in ('automatic_large_gap','automatic_large_contour_gap'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as temp:
                report=acceptance.run_case(case,temp)
                self.assertIsNone(report['error'],report.get('traceback'))
                self.assertTrue(all(report['gates'].values()),report['gates'])
    def test_visible_soil_switch_recovers_short_gap_without_moving_rows(self):
        legacy=dict(acceptance.CASES['short_gap_leaf_overlap'],refine_visible=False)
        name='short_gap_leaf_overlap_legacy_test';acceptance.CASES[name]=legacy
        try:
            with tempfile.TemporaryDirectory() as temp:
                before=acceptance.run_case(name,temp)
                after=acceptance.run_case('short_gap_leaf_overlap',temp)
                self.assertIsNone(before['error'],before.get('traceback'))
                self.assertIsNone(after['error'],after.get('traceback'))
                self.assertFalse(before['gates']['all_near_threshold_gaps_detected'])
                self.assertTrue(all(after['gates'].values()),after['gates'])
                self.assertEqual(before['row_geometry_sha256'],after['row_geometry_sha256'])
                # Read the exported attribute without retaining a pooled OGR
                # connection, which locks TemporaryDirectory files on Windows.
                import sqlite3
                connection=sqlite3.connect(str(Path(temp)/'short_gap_leaf_overlap/gaps.gpkg'))
                try:
                    table=connection.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchone()[0]
                    recovered=connection.execute('SELECT COUNT(*) FROM "'+table.replace('"','""')+'" WHERE evidencia=?',('solo_e_nucleo',)).fetchone()[0]>0
                finally:connection.close()
                self.assertTrue(recovered)
        finally:acceptance.CASES.pop(name,None)
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

