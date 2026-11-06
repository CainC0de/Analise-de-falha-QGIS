"""Rebuild README figures in an initialized QGIS, without changing the project.

Requires the local audit folder produced during validation. Only aggregated
metrics and rendered crops are exported; input paths/coordinates stay local.
"""
import ast
import hashlib
import json
from pathlib import Path
import shutil

from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from qgis.core import (QgsProject, QgsVectorLayer, QgsLineSymbol,
                       QgsMapSettings, QgsMapRendererSequentialJob, QgsRectangle)
from qgis.PyQt.QtCore import QSize

ROOT=Path(__file__).resolve().parents[1]
AUDIT=ROOT.parent/'validacao_centros/revisao_2_6'
IMAGES=ROOT/'DOCS/imagens'
DATA=ROOT/'DOCS/dados'
IMAGES.mkdir(parents=True,exist_ok=True)
DATA.mkdir(parents=True,exist_ok=True)
GREEN='#15805c';ORANGE='#db7742';INK='#203b36';GRAY='#61746e'


def save_figure(figure,name):
    FigureCanvasAgg(figure)
    figure.savefig(str(IMAGES/(name+'.svg')),facecolor='white',bbox_inches='tight')
    svg=IMAGES/(name+'.svg')
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text(encoding='utf-8').splitlines())+'\n',encoding='utf-8')
    preview=AUDIT/'documentation_preview';preview.mkdir(exist_ok=True)
    figure.savefig(str(preview/(name+'.png')),facecolor='white',bbox_inches='tight',dpi=150)


def charts():
    regressions=json.loads((AUDIT/'acceptance_release/regressions.json').read_text())
    matrix=json.loads((AUDIT/'acceptance_release/matrix.json').read_text())
    audit=json.loads((AUDIT/'release_audit.json').read_text())
    before=json.loads((AUDIT/'baseline_comparison/comparison.json').read_text())
    after=json.loads((AUDIT/'release_comparison/comparison.json').read_text())
    for name,digest in regressions['source_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    assert regressions['successful'] and all(r['error'] is None and all(r['gates'].values()) for r in matrix)
    summary={'version':'2.6','date':'2026-11-06','regressions':{'run':regressions['run'],'successful':regressions['successful']},
        'environment':regressions['environment'],'production_sha256':regressions['source_sha256'],
        'scenarios':matrix,'real_audit':{k:{name:v for name,v in item.items() if name not in ('crossing_pairs','gaps_off_associated_row_1mm')}
            |{'crossing_pairs_count':len(item['crossing_pairs']),'off_row_gaps_count':len(item['gaps_off_associated_row_1mm'])} for k,item in audit.items()},
        'agreement_30cm':{'baseline':before['agreement']['0.3'],'revision':after['agreement']['0.3']},
        'common_area_m2':after['common_area_m2'],'note':'Functional tests and spatial agreement; not field accuracy or independent certification.'}
    (DATA/'validacao_2_6.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')

    fig=Figure(figsize=(11.8,4.1),layout='constrained');ax=fig.subplots()
    labels=['Pares de linhas cruzadas','Geometrias inválidas','Falhas fora da linha associada']
    old=audit['baseline_2_5'];new=audit['revised_2_6']
    a=[len(old['crossing_pairs']),old['invalid_rows']+old['invalid_gaps'],len(old['gaps_off_associated_row_1mm'])]
    b=[len(new['crossing_pairs']),new['invalid_rows']+new['invalid_gaps'],len(new['gaps_off_associated_row_1mm'])]
    pos=list(range(3));bars1=ax.barh([p+.18 for p in pos],a,height=.32,color=ORANGE,label='Referência 2.5')
    bars2=ax.barh([p-.18 for p in pos],b,height=.32,color=GREEN,label='Revisão 2.6')
    ax.bar_label(bars1,padding=5,color=INK);ax.bar_label(bars2,padding=5,color=INK)
    ax.set_yticks(pos,labels);ax.invert_yaxis();ax.set_xlim(0,13);ax.set_xticks(range(0,13,2));ax.set_xlabel('Ocorrências na auditoria geométrica')
    ax.set_title('Integridade das linhas no talhão disponível',loc='left',fontsize=16,color=INK,pad=18)
    ax.legend(loc='lower right',frameon=False);ax.spines[['top','right','left']].set_visible(False);ax.grid(axis='x',alpha=.12);ax.set_axisbelow(True)
    fig.supxlabel('Mesmo RGB e nuvem · sem linhas projetadas · mínimo de 50 cm · tolerância de associação: 1 mm',fontsize=9,color=GRAY)
    save_figure(fig,'integridade_geometrica')

    translations={'straight':'Tiro reto com projeto','straight_shifted':'Projeto deslocado 15 cm','contour':'Curva com projeto','oblique':'Oblíqua com projeto',
        'yellow':'Cana amarelada','automatic':'Automático: tiro reto','automatic_healthy':'Automático: controle saudável','automatic_oblique':'Automático: oblíqua',
        'automatic_contour':'Automático: curva','short_gap_leaf_overlap':'Falha de 50 cm + folha lateral',
        'automatic_large_gap':'Automático: ausência de 16 m','automatic_large_contour_gap':'Automático: curva + ausência de 16 m'}
    fig=Figure(figsize=(11.8,6.1),layout='constrained');ax=fig.subplots()
    values=[r['max_length_error_m']*100 for r in matrix]
    bars=ax.barh(range(len(matrix)),values,height=.58,color=GREEN)
    ax.set_yticks(range(len(matrix)),[translations[r['case']] for r in matrix]);ax.invert_yaxis();ax.set_xlim(0,11.7)
    ax.bar_label(bars,labels=[f'{v:.2f}'.replace('.',',') for v in values],padding=5,fontsize=9,color=INK)
    ax.axvline(10,color=ORANGE,linestyle='--',linewidth=1.8,label='Limite de aceitação: 10 cm')
    ax.set_xlabel('Maior erro absoluto de comprimento (cm)');ax.set_title('12 cenários completos aprovados',loc='left',fontsize=16,color=INK,pad=18)
    ax.spines[['top','right','left']].set_visible(False);ax.grid(axis='x',alpha=.12);ax.set_axisbelow(True);ax.legend(loc='lower right',frameon=True,facecolor='white',edgecolor='none',framealpha=1.)
    fig.supxlabel('Verdade geométrica sintética definida antes da execução · não estima acurácia de campo',fontsize=9,color=GRAY)
    save_figure(fig,'validacao_sintetica')

    fig=Figure(figsize=(11.8,4.3),layout='constrained');ax=fig.subplots()
    keys=['ours_covered_pct','inforow_covered_pct'];a=[before['agreement']['0.3'][k] for k in keys];b=[after['agreement']['0.3'][k] for k in keys]
    bar1=ax.bar([-.18,.82],a,width=.32,color=ORANGE,label='Plugin 2.5');bar2=ax.bar([.18,1.18],b,width=.32,color=GREEN,label='Plugin 2.6')
    ax.bar_label(bar1,labels=[f'{v:.2f}%'.replace('.',',') for v in a],padding=5,color=INK);ax.bar_label(bar2,labels=[f'{v:.2f}%'.replace('.',',') for v in b],padding=5,color=INK)
    ax.set_xticks([0,1],['Comprimento do plugin coberto pelo Inforow','Comprimento do Inforow coberto pelo plugin'])
    ax.set_ylim(0,100);ax.set_ylabel('Concordância de comprimento (%)');ax.set_title('Comparação espacial com o Inforow',loc='left',fontsize=16,color=INK,pad=18)
    ax.legend(loc='upper right',frameon=False);ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.12);ax.set_axisbelow(True)
    fig.supxlabel('Mesma área válida · mínimo de 50 cm · corredor de 30 cm · concordância não equivale a precisão/recall de campo',fontsize=9,color=GRAY)
    save_figure(fig,'comparacao_inforow')


def maps():
    project=QgsProject.instance()
    rgb=next(layer for layer in project.mapLayers().values() if layer.name()=='Recortado (mascara)')
    assert rgb.isValid()
    centre=rgb.extent().center();extent=QgsRectangle(centre.x()-42,centre.y()-21,centre.x()+42,centre.y()+21)
    rows=QgsVectorLayer(str(AUDIT/'release/rows.gpkg'),'rows','ogr')
    gaps=QgsVectorLayer(str(AUDIT/'release/gaps.gpkg'),'gaps','ogr')
    assert rows.isValid() and gaps.isValid()
    rows.renderer().setSymbol(QgsLineSymbol.createSimple({'line_color':'0,210,135','line_width':'.25'}))
    gaps.renderer().setSymbol(QgsLineSymbol.createSimple({'line_color':'255,115,25','line_width':'.55'}))
    for name,layers in [('ortomosaico_rgb',[rgb]),('linhas_e_falhas',[gaps,rows,rgb])]:
        settings=QgsMapSettings();settings.setDestinationCrs(rgb.crs());settings.setLayers(layers)
        settings.setExtent(extent);settings.setOutputSize(QSize(1600,800))
        job=QgsMapRendererSequentialJob(settings);job.start();job.waitForFinished()
        assert job.renderedImage().save(str(IMAGES/(name+'.jpg')),'JPG',92)
    shutil.copyfile(AUDIT/'comparacao_pontas.png',IMAGES/'antes_depois_pontas.png')


def inventory():
    chapters={
        '__init__.py':'00_ARQUITETURA_E_FLUXO.md','Falhadeplantio.py':'00_ARQUITETURA_E_FLUXO.md',
        'Falhadeplantio_provider.py':'00_ARQUITETURA_E_FLUXO.md',
        'Falhadeplantio_algorithm.py':'03_CLASSIFICACAO_RGB.md','RestituirLinhasAlgorithm.py':'06_RASTREAMENTO_DAS_LINHAS.md',
        'cane_centers.py':'07_CENTROS_E_AJUSTE.md','planting_gaps.py':'09_IDENTIFICACAO_DE_FALHAS.md','row_network.py':'08_CONTINUIDADE_E_PROJECOES.md'}
    records=[];lines=['## Inventário das declarações\n','| Arquivo | Função ou método | Guia principal |','| --- | --- | --- |']
    for name,chapter in chapters.items():
        tree=ast.parse((ROOT/name).read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                records.append((name,node.name,node.lineno,chapter))
            elif isinstance(node,ast.ClassDef):
                records.extend((name,node.name+'.'+method.name,method.lineno,chapter) for method in node.body if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)))
    overrides={'initAlgorithm':'01_ENTRADAS_PARAMETROS_CRS.md',
        '_warp_progress':'02_PREPARACAO_RECORTE_RASTER.md','_prepare_cutline':'02_PREPARACAO_RECORTE_RASTER.md',
        '_estimate_metric_pixel_size':'02_PREPARACAO_RECORTE_RASTER.md','_local_utm_crs':'01_ENTRADAS_PARAMETROS_CRS.md',
        '_accumulate_points_grid':'05_GRADES_FUSAO_ORIENTACAO.md','_splat_points':'05_GRADES_FUSAO_ORIENTACAO.md',
        '_extract_raster_crop_grid':'05_GRADES_FUSAO_ORIENTACAO.md','_classify_rgb_grid':'05_GRADES_FUSAO_ORIENTACAO.md',
        '_fuse_point_and_raster_density':'05_GRADES_FUSAO_ORIENTACAO.md','_build_local_orientation_field':'05_GRADES_FUSAO_ORIENTACAO.md',
        '_steerable_ridge_filter_tiled':'05_GRADES_FUSAO_ORIENTACAO.md','_reconstruct_from_planned_lines':'07_CENTROS_E_AJUSTE.md',
        '_offsets_from_plant_centers':'07_CENTROS_E_AJUSTE.md','_remeasure_gaps':'10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md',
        '_measure_line_gaps':'10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md','intervals_from_states':'10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md',
        'sample_polyline':'10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md','review_intervals':'10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md',
        'segment_coordinates':'10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md'}
    for name,function,number,chapter in records:
        chapter=overrides.get(function.rsplit('.',1)[-1],chapter)
        lines.append(f'| [{name}](../{name}#L{number}) | `{function}` | [Explicação]({chapter}) |')
    lines+=['','## Assinaturas dos arquivos documentados','', '| Arquivo | SHA-256 |','| --- | --- |']
    for name in chapters:
        lines.append(f'| `{name}` | `{hashlib.sha256((ROOT/name).read_bytes()).hexdigest()}` |')
    path=ROOT/'DOCS/13_MAPA_DO_CODIGO.md';base=path.read_text(encoding='utf-8').split('<!-- INVENTARIO_GERADO -->')[0]
    path.write_text(base+'<!-- INVENTARIO_GERADO -->\n\n'+'\n'.join(lines)+'\n',encoding='utf-8')
    return len(records)


def build():
    charts();maps();count=inventory()
    print(json.dumps({'images':6,'functions_documented':count,'production_code_changed':False}))


if __name__=='__main__':build()
