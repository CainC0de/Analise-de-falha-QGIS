"""Positive inference and refusal controls, separate from the acceptance fixtures."""
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('row_network_test_loader',ROOT/'scripts/validate_acceptance_qgis.py')
loader=importlib.util.module_from_spec(spec);spec.loader.exec_module(loader)
_,Algorithm=loader.load_algorithms()
network=sys.modules[Algorithm.__module__.rsplit('.',1)[0]+'.row_network']

class Feedback:
    def isCanceled(self):return False

class Sampler:
    res=.05

class RowNetworkTests(unittest.TestCase):
    def lines(self,offsets):
        u=np.linspace(0,24,241)
        return [np.column_stack([u,np.full_like(u,v)]) for v in offsets]

    def test_regular_interior_gap_infers_exactly_one_row(self):
        parts,origins=network.complete_network(self.lines([0,1.5,4.5,6]),1.5,Sampler(),Feedback())
        self.assertEqual(len(parts),5)
        self.assertEqual(origins.count('inferida_entre_vizinhas'),1)
        self.assertAlmostEqual(float(np.median(parts[-1][:,1])),3.)

    def test_irregular_spacing_does_not_create_a_row(self):
        parts,origins=network.complete_network(self.lines([0,1.5,4.,5.5]),1.5,Sampler(),Feedback())
        self.assertEqual(len(parts),4)
        self.assertNotIn('inferida_entre_vizinhas',origins)

    def test_regular_rows_do_not_create_outer_rows_or_duplicates(self):
        parts,origins=network.complete_network(self.lines([0,1.5,3,4.5]),1.5,Sampler(),Feedback())
        self.assertEqual(len(parts),4)
        self.assertNotIn('inferida_entre_vizinhas',origins)

    def test_different_directions_do_not_share_completion_model(self):
        a=self.lines([0])[0];b=np.column_stack([np.full(241,3.),np.linspace(0,24,241)])
        parts,origins=network.complete_network([a,b],1.5,Sampler(),Feedback())
        self.assertEqual(len(parts),2)
        self.assertNotIn('inferida_entre_vizinhas',origins)

    def test_short_overlap_cannot_support_missing_row(self):
        a=self.lines([0])[0];b=np.column_stack([np.linspace(21,45,241),np.full(241,3.)])
        parts,origins=network.complete_network([a,b],1.5,Sampler(),Feedback())
        self.assertEqual(len(parts),2)
        self.assertNotIn('inferida_entre_vizinhas',origins)

    def test_single_supported_row_cannot_register_an_empty_reference(self):
        from qgis.core import QgsPointXY
        references=self.lines([0,1.5,3]);p=references[0]+[0,.15]
        observed=([QgsPointXY(x,y) for x,y in p],0.,24.,0.,0.,0,100.,0.)
        empty=([QgsPointXY(x,y) for x,y in references[1]],0.,24.,0.,0.,0,0.,100.)
        rows,origins=network.register_empty_rows([observed,empty],references,['projeto']*2,1.5)
        self.assertEqual(origins,['projeto']*2)
        self.assertEqual(rows[1][0][0].y(),1.5)

    def test_two_vertex_projects_support_finite_consensus_registration(self):
        from qgis.core import QgsPointXY
        references=[p[[0,-1]] for p in self.lines([0,1.5,3,4.5])]
        rows=[]
        for index,p in enumerate(self.lines([0,1.5,3,4.5])):
            if index<3:p=p+[0,.15]
            rows.append(([QgsPointXY(x,y) for x,y in p],0.,24.,0.,0.,0,
                         100. if index<3 else 0.,0. if index<3 else 100.))
        registered,origins=network.register_empty_rows(rows,references,['projeto']*4,1.5)
        self.assertEqual(origins[-1],'projeto_registrado')
        self.assertAlmostEqual(registered[-1][0][0].y(),4.65,places=6)
