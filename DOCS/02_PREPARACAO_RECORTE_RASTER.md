# 02 — Preparação, recorte e leitura do raster

[Índice](README.md) · Fonte principal: [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py), `processAlgorithm()`, `_prepare_cutline()`, `_estimate_metric_pixel_size()` e `_local_utm_crs()`.

## Sequência da preparação

1. Abrir a camada QGIS e o dataset GDAL; validar bandas e projeção.
2. Resolver o CRS métrico de saída.
3. Calcular a resolução efetiva.
4. Identificar alpha: entre bandas não selecionadas como RGB, a primeira com interpretação alpha ou índice físico 4 é usada.
5. Criar `rgb_input.vrt` com as bandas selecionadas em ordem R/G/B e alpha, quando disponível.
6. Se necessário, executar `gdal.Warp` para preparar a grade.
7. Abrir a grade preparada e alimentar a classificação e os pontos com os mesmos blocos.

## Resolução efetiva

Sem troca de CRS, as dimensões dos vetores do geotransform são:

```text
largura = hypot(gt[1], gt[4])
altura  = hypot(gt[2], gt[5])
resolução nativa = min(largura, altura), convertida para metros
```

Se o pedido for menor que 95% dessa resolução, o código conserva a resolução nativa. Nos outros casos, usa o pedido. A tolerância de 5% é parte da implementação; não significa geração de informação nova.

Com reprojeção, `_estimate_metric_pixel_size()` transforma a extensão e estima o menor valor entre largura métrica/número de colunas e altura métrica/número de linhas. Se essa estimativa falhar, devolve 0,05 m. O pixel escolhido em centímetros é `max(pedido, 0,95 × estimativa_nativa × 100)`.

O Warp é acionado por recorte, troca de CRS, diferença superior a 5% na comparação do pixel escolhido com `abs(gt[1])`, ou rotação do geotransform. Essa condição não compara separadamente todos os componentes de um pixel anisotrópico.

## Uso direto e uso com máscara

| Situação | Materialização |
| --- | --- |
| Uso direto sem necessidade de Warp | VRT de bandas |
| Uso direto com reprojeção/regradeamento | VRT reprojetado |
| Recorte pelo talhão | GeoTIFF RGB persistente ou temporário escolhido pelo Processing |

O reamostrador da preparação RGB é **bilinear**. No modo recortado, a criação usa `TILED=YES`, `COMPRESS=DEFLATE` e `BIGTIFF=IF_SAFER`.

## Preparação do polígono

`_prepare_cutline()` percorre as feições sem atributos e:

- ignora geometrias nulas/vazias;
- recusa geometrias inválidas, em vez de corrigi-las silenciosamente;
- transforma cada geometria ao CRS de saída;
- converte para multipartes e grava em camada temporária `mask` de um GeoPackage;
- calcula a interseção das extensões da máscara e do raster transformado;
- reúne os polígonos em uma união geométrica para conferir os centroides dos pontos.

Uma camada sem polígonos utilizáveis ou com extensões sem interseção é recusada. A conferência inicial por extensão é uma aproximação retangular; a cutline efetiva e a validade dos blocos determinam o conteúdo aproveitado.

No Warp, `outputBounds` recebe os limites recortados, `cutlineDSName` aponta para a máscara, `srcAlpha` respeita a alpha identificada e `dstAlpha=True` gera transparência. Partes separadas e buracos permanecem na geometria da cutline.

## Validade dos pixels

Na classificação, um pixel é utilizável quando:

```text
R, G e B são finitos
e cada banda difere de seu NoData declarado, quando houver
e alpha > 0, quando houver alpha
e pelo menos uma banda RGB é maior que zero
```

Um bloco sem pixels válidos na região interna recebe integralmente 255 no classificado. Exterior e buracos do recorte não devem gerar pontos. Além da máscara raster, o centroide de cada ponto é conferido contra a união poligonal.

## Carregamento e ciclo de vida

O classificado e a nuvem são sempre gerados a partir da imagem preparada, sem uma segunda importação. No modo recortado, o dicionário de resultados inclui `OUTPUT_CLIPPED`.

Quando a execução gráfica solicita carregar resultados por `QgsProcessingOutputLayerDefinition`, o código também agenda o RGB preparado para carregamento, inclusive quando seu destino foi gerado automaticamente. Uma chamada apenas computacional de `processAlgorithm()` não implica esse carregamento na interface.

Os VRTs e a cutline de trabalho ficam em `TemporaryDirectory`. O RGB final recortado é um destino separado; não fica no diretório transitório usado apenas para a cutline. Arquivos parciais podem existir se a execução for cancelada após sua criação.
