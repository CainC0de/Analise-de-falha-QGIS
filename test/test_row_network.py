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
    def test_unverified_fragments_cannot_extrapolate_through_each_other(self):
        a=np.column_stack([np.linspace(0,9,91),np.zeros(91)])
        b=np.column_stack([np.linspace(10,24,141),np.full(141,.1)])
        parts=[a,b]+self.lines([1.5,3.])
        completed,_=network.complete_network(parts,1.5,Sampler(),Feedback())
        self.assertLess(completed[0][:,0].max(),completed[1][:,0].min())

    def test_other_orientation_family_blocks_inference_over_existing_fragment(self):
        parts=self.lines([0,1.5,4.5,6])
        parts.append(np.array([[8.,2.],[10.,4.]]))
        completed,origins=network.complete_network(parts,1.5,Sampler(),Feedback())
        self.assertEqual(len(completed),5)
        self.assertNotIn('inferida_entre_vizinhas',origins)

    def test_existing_short_fragment_blocks_duplicate_inferred_row(self):
        parts=self.lines([0,1.5,4.5,6])
        parts.append(np.column_stack([np.linspace(8,10.5,26),np.full(26,3.)]))
        completed,origins=network.complete_network(parts,1.5,Sampler(),Feedback())
        self.assertEqual(len(completed),5)
        self.assertNotIn('inferida_entre_vizinhas',origins)

    def test_endpoint_noise_is_not_quadratically_extrapolated_across_neighbour(self):
        from qgis.core import QgsGeometry,QgsPointXY
        parts=self.lines([0,1.5,3.,4.5]);parts[1]=parts[1][:121].copy()
        u=parts[1][:,0];parts[1][:,1]+=.20*np.maximum(0,u-11.5)**2/.5**2
        completed,_=network.complete_network(parts,1.5,Sampler(),Feedback())
        geoms=[QgsGeometry.fromPolylineXY([QgsPointXY(float(x),float(y)) for x,y in p]) for p in completed]
        self.assertFalse(geoms[1].crosses(geoms[2]))

    def fragmented(self):
        u=np.linspace(0,40,401)
        a=np.column_stack([u[u<=8],np.full((u<=8).sum(),3.)])
        b=np.column_stack([u[u>=28],np.full((u>=28).sum(),3.)])
        guides=[np.column_stack([u,np.full_like(u,v)]) for v in (1.5,4.5)]
        parts=[a,b]+guides
        return parts,[np.ones(len(p),bool) for p in parts]

    def test_fragment_bridge_requires_guides_on_both_sides(self):
        parts,support=self.fragmented()
        joined,weights,origins=network.connect_observed_fragments(parts,1.5,Feedback(),support)
        self.assertEqual(len(joined),3)
        self.assertEqual(origins.count('observada_conectada'),1)
        i=origins.index('observada_conectada');line=joined[i]
        self.assertAlmostEqual(network.stationing(line)[-1],40.)
        np.testing.assert_allclose(line[:,1],3.)
        self.assertFalse(weights[i][(line[:,0]>8)&(line[:,0]<28)].any())

    def test_fragments_without_bracketing_guides_are_not_joined(self):
        parts,support=self.fragmented()
        for chosen in ([0,1],[0,1,2]):
            joined,_,origins=network.connect_observed_fragments([parts[i] for i in chosen],
                1.5,Feedback(),[support[i] for i in chosen])
            self.assertEqual(len(joined),len(chosen))
            self.assertNotIn('observada_conectada',origins)

    def test_fragment_bridge_preserves_observed_contour_shape(self):
        parts,support=self.fragmented()
        for p in parts:p[:,1]+=.85*np.sin(2*np.pi*p[:,0]/40.)
        joined,_,origins=network.connect_observed_fragments(parts,1.5,Feedback(),support)
        self.assertEqual(len(joined),3)
        line=joined[origins.index('observada_conectada')]
        np.testing.assert_allclose(line[:,1],3.+.85*np.sin(2*np.pi*line[:,0]/40.),atol=.003)

    def test_fragment_bridge_rejects_a_different_planting_lane(self):
        parts,support=self.fragmented();parts[1]=parts[1]+[0,.65]
        joined,_,_=network.connect_observed_fragments(parts,1.5,Feedback(),support)
        self.assertEqual(len(joined),4)

    def test_fragment_bridge_rejects_guides_without_observed_support(self):
        parts,support=self.fragmented();support[2][:]=False;support[3][:]=False
        joined,_,_=network.connect_observed_fragments(parts,1.5,Feedback(),support)
        self.assertEqual(len(joined),4)

    def test_other_field_direction_does_not_disable_local_row_completion(self):
        parts=self.lines([0,1.5,4.5,6])
        parts.append(np.column_stack([np.full(241,100.),np.linspace(0,24,241)]))
        completed,origins=network.complete_network(parts,1.5,Sampler(),Feedback())
        self.assertEqual(len(completed),6)
        self.assertEqual(origins.count('inferida_entre_vizinhas'),1)

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
