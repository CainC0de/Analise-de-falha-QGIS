"""Acceptance measurements with independent synthetic geometry/presence truth.

Run inside an initialized QGIS Python session, never as a second QApplication.
No project layers are edited. Inforow is not used as ground truth.
"""
import hashlib
import importlib
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import time
import types
import unittest

import numpy as np
from osgeo import gdal, osr
from scipy.spatial import cKDTree
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry,
    QgsPointXY, QgsProcessingContext, QgsProcessingFeedback, QgsProcessingUtils,
    QgsProject, QgsVectorLayer, QgsVectorFileWriter)

ROOT=Path(__file__).resolve().parents[1]
CASES={
    'straight':dict(curved=False,angle=0,colour=[40,150,30],planned=True,shift=0.),
    'straight_shifted':dict(curved=False,angle=0,colour=[40,150,30],planned=True,shift=.15),
    'contour':dict(curved=True,angle=0,colour=[40,150,30],planned=True,shift=0.),
    'oblique':dict(curved=False,angle=33,colour=[40,150,30],planned=True,shift=0.),
    'yellow':dict(curved=False,angle=0,colour=[190,175,70],planned=True,shift=0.),
    'automatic':dict(curved=False,angle=0,colour=[40,150,30],planned=False,shift=0.),
    'automatic_healthy':dict(curved=False,angle=0,colour=[40,150,30],planned=False,shift=0.,healthy=True),
    'automatic_oblique':dict(curved=False,angle=33,colour=[40,150,30],planned=False,shift=0.),
    'automatic_contour':dict(curved=True,angle=0,colour=[40,150,30],planned=False,shift=0.),
    'short_gap_leaf_overlap':dict(curved=False,angle=0,colour=[40,150,30],planned=True,shift=0.,peripheral_leaf=True),
}

def load_algorithms():
    digest=hashlib.sha256(str(ROOT).encode())
    for name in ('Falhadeplantio_algorithm.py','RestituirLinhasAlgorithm.py','planting_gaps.py','cane_centers.py','row_network.py'):
        digest.update((ROOT/name).read_bytes())
    package='acceptance_'+digest.hexdigest()[:12]
    if package not in sys.modules:
        pkg=types.ModuleType(package);pkg.__path__=[str(ROOT)];sys.modules[package]=pkg
    return (importlib.import_module(package+'.Falhadeplantio_algorithm').FalhaDePlantioAlgorithm,
            importlib.import_module(package+'.RestituirLinhasAlgorithm').RestituirLinhasAlgorithm)

def run_regressions(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    suite=unittest.TestSuite()
    for name in ('test_planting_gaps','test_cane_centers','test_rgb_preparation','test_acceptance_pipeline','test_row_network'):
        spec=importlib.util.spec_from_file_location('acceptance_'+name,ROOT/'test'/f'{name}.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    class Result(unittest.TextTestResult):
        def startTest(self,test):
            self.started=time.perf_counter();super().startTest(test)
        def stopTest(self,test):
            records.append({'test':test.id(),'seconds':time.perf_counter()-self.started})
            super().stopTest(test)
    records=[];stream=io.StringIO();started=time.perf_counter()
    result=unittest.TextTestRunner(stream=stream,resultclass=Result,verbosity=2).run(suite)
    (output/'regressions.txt').write_text(stream.getvalue(),encoding='utf-8')
    report={'run':result.testsRun,'failures':[(t.id(),s) for t,s in result.failures],
        'errors':[(t.id(),s) for t,s in result.errors],'skipped':[(t.id(),s) for t,s in result.skipped],
        'successful':result.wasSuccessful(),'seconds':time.perf_counter()-started,'tests':records,
        'environment':{'qgis':Qgis.QGIS_VERSION,'python':sys.version,'gdal':gdal.VersionInfo()},
        'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [ROOT/'planting_gaps.py',ROOT/'cane_centers.py',ROOT/'RestituirLinhasAlgorithm.py',ROOT/'Falhadeplantio_algorithm.py',ROOT/'row_network.py']}}
    (output/'regressions.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return {k:v for k,v in report.items() if k not in ('tests','source_sha256')}

def curve(u,curved):
    return .85*np.sin(2*np.pi*np.asarray(u)/32) if curved else np.zeros_like(np.asarray(u),dtype=float)

def transform(u,v,angle):
    a=math.radians(angle);u=np.asarray(u);v=np.asarray(v)
    return np.stack([600000+u*np.cos(a)-v*np.sin(a),8090000+u*np.sin(a)+v*np.cos(a)],axis=-1)

def geom(xy):
    return QgsGeometry.fromPolylineXY([QgsPointXY(float(x),float(y)) for x,y in xy])

def make_fixture(directory,config):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    # Five rows, including one entirely empty and one completely planted row.
    gaps=[[(5,5.5),(10,10.95),(20,22)],[(0,1),(8,9.5),(24,26)],[(0,32)],[],[(15,16.5)]]
    if config.get('healthy'):gaps=[[] for _ in range(5)]
    u=np.linspace(0,32,1601);truth=[];references=[];expected=[]
    for row in range(5):
        v=2+row*1.5+curve(u,config['curved'])
        truth.append(geom(transform(u,v,config['angle'])))
        references.append(geom(transform(u,v+config['shift'],config['angle'])))
        for a,b in gaps[row]:
            uu=np.linspace(a,b,max(2,int((b-a)/.02)+1))
            expected.append((row,geom(transform(uu,2+row*1.5+curve(uu,config['curved']),config['angle']))))
    corners=transform(np.array([-1,33,33,-1]),np.array([0,0,10,10]),config['angle'])
    resolution=.05;xmin=math.floor(corners[:,0].min()/resolution)*resolution
    ymax=math.ceil(corners[:,1].max()/resolution)*resolution
    width=int(math.ceil((corners[:,0].max()-xmin)/resolution));height=int(math.ceil((ymax-corners[:,1].min())/resolution))
    yy,xx=np.mgrid[:height,:width];x=xmin+(xx+.5)*resolution;y=ymax-(yy+.5)*resolution
    angle=math.radians(config['angle']);uu=(x-600000)*math.cos(angle)+(y-8090000)*math.sin(angle)
    vv=-(x-600000)*math.sin(angle)+(y-8090000)*math.cos(angle)
    valid=(uu>=0)&(uu<32)&(vv>=0)&(vv<=10);crop=np.zeros(valid.shape,bool)
    for row in range(5):
        occupied=np.ones(valid.shape,bool)
        for a,b in gaps[row]:occupied &= ~((uu>=a)&(uu<b))
        crop |= occupied & (abs(vv-(2+row*1.5+curve(uu,config['curved'])))<.15)
    crop &= valid
    if config.get('peripheral_leaf'):
        # A lateral leaf crosses the 50 cm gap on row zero; the true gap and
        # its planting axis remain unchanged. This is not a plant at its centre.
        crop |= valid&(uu>=4.)&(uu<6.)&(abs(vv-(2.+curve(uu,config['curved'])+.27))<.035)
    raster=directory/'rgb.tif';ds=gdal.GetDriverByName('GTiff').Create(str(raster),width,height,4,gdal.GDT_Byte)
    ds.SetGeoTransform((xmin,resolution,0,ymax,0,-resolution));srs=osr.SpatialReference();srs.ImportFromEPSG(31982);ds.SetProjection(srs.ExportToWkt())
    for i,(soil,cane,interp) in enumerate(zip([168,152,125],config['colour'],[gdal.GCI_RedBand,gdal.GCI_GreenBand,gdal.GCI_BlueBand]),1):
        ds.GetRasterBand(i).WriteArray(np.where(crop,cane,soil).astype(np.uint8));ds.GetRasterBand(i).SetColorInterpretation(interp)
    ds.GetRasterBand(4).WriteArray((valid*255).astype(np.uint8));ds.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand);ds=None
    layer=QgsVectorLayer('LineString?crs=EPSG:31982','acceptance_reference','memory');features=[]
    for geometry in references:
        f=QgsFeature();f.setGeometry(geometry);features.append(f)
    layer.dataProvider().addFeatures(features);layer.updateExtents()
    (directory/'truth.json').write_text(json.dumps({'config':config,'row_count':5,'pixel_m':resolution,
        'gaps_u_m':gaps,'truth_wkt':[g.asWkt(8) for g in truth],
        'expected_gap_wkt':[(i,g.asWkt(8)) for i,g in expected]},indent=2),encoding='utf-8')
    return raster,layer,truth,expected

def audit(rows,segments,truth,expected):
    lines=[f.geometry() for f in rows.getFeatures()];detected=[f.geometry() for f in segments.getFeatures()]
    points=[];owners=[]
    for i,line in enumerate(truth):
        for s in np.arange(0,line.length(),.05):
            p=line.interpolate(float(s)).asPoint();points.append((p.x(),p.y()));owners.append(i)
    tree=cKDTree(points);owners=np.asarray(owners);errors=[];assigned=[[] for _ in truth]
    for line in lines:
        sampled=[line.interpolate(float(s)).asPoint() for s in np.arange(0,line.length(),.10)]
        if not sampled:continue
        distances,indices=tree.query([(p.x(),p.y()) for p in sampled]);owner=int(np.bincount(owners[indices]).argmax())
        assigned[owner].append(line)
        errors.extend([QgsGeometry.fromPointXY(p).distance(truth[owner]) for p in sampled])
    tolerance=.10
    corridors=[g.buffer(tolerance,6) for g in lines]
    union=QgsGeometry.unaryUnion(corridors) if corridors else QgsGeometry()
    cover=[line.intersection(union).length()/line.length() if corridors else 0. for line in truth]
    # Match gaps to independent geometry by overlap; one-to-one assignments.
    candidates=[]
    for i,(_,target) in enumerate(expected):
        for j,pred in enumerate(detected):
            overlap=target.intersection(pred.buffer(tolerance,6)).length()
            if overlap/target.length()>=.70 and overlap/pred.length()>=.70:candidates.append((overlap,i,j))
    used_true=set();used_pred=set();matches=[]
    for overlap,i,j in sorted(candidates,reverse=True):
        if i in used_true or j in used_pred:continue
        used_true.add(i);used_pred.add(j);matches.append((i,j))
    # Exact 50 cm is reported separately AND remains a required gate. Splitting
    # it out must not turn a missed minimum-size gap into a passing result.
    evaluable=[i for i,(_,g) in enumerate(expected) if g.length()>=.60]
    matched_evaluable=[(i,j) for i,j in matches if i in evaluable]
    near=[i for i,(_,g) in enumerate(expected) if g.length()<.60]
    duplicate=sum(max(0,len(part)-1) for part in assigned)
    crossing=sum(lines[i].crosses(lines[j]) for i in range(len(lines)) for j in range(i))
    return {'rows':len(lines),'expected_rows':len(truth),'assigned_parts_per_row':[len(p) for p in assigned],
        'row_geometry_sha256':hashlib.sha256(b''.join(bytes(g.asWkb()) for g in lines)).hexdigest(),
        'origins':{key:sum(f['origem']==key for f in rows.getFeatures()) for key in
            set(f['origem'] for f in rows.getFeatures())} if 'origem' in rows.fields().names() else {},
        'invalid_rows':sum(not g.isGeosValid() for g in lines),'crossing_pairs':crossing,
        'extra_parts':duplicate,'row_coverage_within_10cm':cover,
        'row_deviation_p95_m':float(np.percentile(errors,95)) if errors else None,
        'row_deviation_max_m':float(max(errors)) if errors else None,
        'expected_gaps':len(expected),'detected_gaps':len(detected),'matched_gaps':len(matches),
        'evaluable_expected_gaps':len(evaluable),'evaluable_matched_gaps':len(matched_evaluable),
        'near_threshold_expected':len(near),'near_threshold_matched':len([i for i in near if i in used_true]),
        'unmatched_predictions':len(detected)-len(used_pred),
        'gap_length_max_absolute_error_m':float(max((abs(expected[i][1].length()-detected[j].length()) for i,j in matches),default=0)),
        'minimum_detected_gap_m':float(min((g.length() for g in detected),default=0)),
        'matched_expected_indices':sorted(used_true),
        'matches':[{'expected_index':i,'row':expected[i][0],
            'expected_m':expected[i][1].length(),'detected_m':detected[j].length(),
            'absolute_error_m':abs(expected[i][1].length()-detected[j].length())} for i,j in matches],
        'gates':{'valid_geometry':all(g.isGeosValid() for g in lines) and bool(lines),
            'no_crossings':crossing==0,'one_part_per_row':len(lines)==len(truth) and all(len(p)==1 for p in assigned),
            'row_coverage_95pct_within_10cm':all(c>=.95 for c in cover),
            'all_gaps_above_60cm_detected':len(matched_evaluable)==len(evaluable),
            'all_near_threshold_gaps_detected':all(i in used_true for i in near),
            'no_unmatched_gap_predictions':len(detected)==len(used_pred),
            'gap_length_error_at_most_10cm':all(abs(expected[i][1].length()-detected[j].length())<=.10+1e-6 for i,j in matches),
            'minimum_50cm_respected':all(g.length()>=.5-1e-6 for g in detected)}}

def run_case(name,output):
    started=time.perf_counter();directory=Path(output)/name;directory.mkdir(parents=True,exist_ok=True)
    config=CASES[name];report={'case':name,'config':config,'error':None}
    context=QgsProcessingContext();context.setProject(QgsProject.instance());feedback=QgsProcessingFeedback()
    try:
        raster,planned,truth,expected=make_fixture(directory,config)
        First,Second=load_algorithms();first=First();first.initAlgorithm()
        res=first.processAlgorithm({'INPUT_RASTER':str(raster),'PIXEL_SIZE_CM':5.,'POINT_SPACING_CM':10.,
            'GLI_THRESHOLD':0.,'OUTPUT':str(directory/'classified.tif'),'OUTPUT_POINTS':'memory:'},context,feedback)
        cloud=QgsProcessingUtils.mapLayerFromString(res['OUTPUT_POINTS'],context)
        report['point_count']=cloud.featureCount()
        context.temporaryLayerStore().addMapLayer(planned)
        second=Second();second.initAlgorithm()
        params={'INPUT_RASTER':str(raster),'INPUT_POINTS':cloud.id(),'MIN_GAP_CM':50.,'ROW_SPACING':1.5,
            'OUTPUT':'memory:','OUTPUT_GAPS':'memory:','OUTPUT_REVIEW':'memory:',
            'REFINE_VISIBLE_GAPS':config.get('refine_visible',True)}
        if config['planned']:params['INPUT_PLANNED_LINES']=planned.id()
        res=second.processAlgorithm(params,context,feedback)
        rows=QgsProcessingUtils.mapLayerFromString(res['OUTPUT'],context)
        gaps=QgsProcessingUtils.mapLayerFromString(res['OUTPUT_GAPS'],context)
        report.update(audit(rows,gaps,truth,expected))
        for layer,name in ((rows,'rows'),(gaps,'gaps')):
            options=QgsVectorFileWriter.SaveVectorOptions();options.driverName='GPKG'
            written=QgsVectorFileWriter.writeAsVectorFormatV3(layer,str(directory/f'{name}.gpkg'),context.transformContext(),options)
            if written[0]!=QgsVectorFileWriter.NoError:raise RuntimeError(str(written))
    except Exception as exc:
        import traceback
        report['error']=str(exc);report['traceback']=traceback.format_exc()
    finally:
        report['seconds']=time.perf_counter()-started
        (directory/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        context.temporaryLayerStore().removeAllMapLayers()
    return report
