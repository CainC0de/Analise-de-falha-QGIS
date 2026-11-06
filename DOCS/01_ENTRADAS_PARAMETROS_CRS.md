# 01 — Entradas, parâmetros e sistemas de referência

[Índice](README.md) · Fontes: `initAlgorithm()` e `processAlgorithm()` em [classificação](../Falhadeplantio_algorithm.py) e [restituição](../RestituirLinhasAlgorithm.py).

## Classificar vegetação verde

| Chave | Padrão / faixa no diálogo | Efeito |
| --- | --- | --- |
| `INPUT_RASTER` | Obrigatório | Imagem com três bandas RGB distintas utilizáveis |
| `PREPARATION_MODE` | `0`; opções 0 e 1 | Uso direto ou recorte pelo polígono |
| `MASK_LAYER` | Opcional no diálogo | Obrigatório no modo 1; fonte poligonal com CRS válido |
| `TARGET_CRS` | Vazio | CRS de saída explícito, projetado em metros |
| `RED_BAND` | 1; mínimo 1 | Número da banda R na imagem original |
| `GREEN_BAND` | 2; mínimo 1 | Número da banda G |
| `BLUE_BAND` | 3; mínimo 1 | Número da banda B |
| `PIXEL_SIZE_CM` | 5; mínimo 0,5 cm | Resolução solicitada da grade preparada/classificada |
| `POINT_SPACING_CM` | 20; 5–200 cm | Tamanho solicitado da célula de agregação da nuvem |
| `GLI_THRESHOLD` | 0; −1 a 1 | Ajuste aditivo dos limiares espectrais e locais |
| `OUTPUT` | Obrigatório | GeoTIFF classificado |
| `OUTPUT_POINTS` | Obrigatório | Sink de pontos |
| `OUTPUT_CLIPPED` | Opcional, não criado por padrão | RGB preparado no modo de recorte; caminho vazio gera temporário |

Os números RGB devem existir e ser diferentes. O algoritmo valida o raster, seu CRS e sua projeção GDAL. Arquivos original, classificado e RGB recortado não podem resolver para o mesmo caminho.

`PIXEL_SIZE_CM` e `POINT_SPACING_CM` têm efeitos distintos. Exemplo: pixel de 3 cm e célula de pontos de aproximadamente 20 cm não produzem um ponto para cada pixel de 3 cm. A conversão e o arredondamento estão nos guias [02](02_PREPARACAO_RECORTE_RASTER.md) e [04](04_NUVEM_DE_PONTOS.md).

## Restituir linhas e medir falhas

| Chave | Padrão / faixa no diálogo | Efeito |
| --- | --- | --- |
| `INPUT_RASTER` | Obrigatório | Imagem de referência; RGB conserva a evidência de cor |
| `INPUT_POINTS` | Obrigatório | Camada pontual em CRS projetado em metros |
| `INPUT_PLANNED_LINES` | Opcional | Referência geométrica externa; ausência ativa o modo automático |
| `ROW_SPACING` | 1,5; 0,5–4 m | Escala esperada entre fileiras, usada em orientação, corredores e rede |
| `MAX_DEVIATION` | 1; 0,05–1,5 m/m | Limita busca lateral por avanço no rastreamento automático |
| `MAX_GAP` | 10; 0,5–20 m | Lacuna tolerada pelo rastreador; também participa dos limites da rede |
| `MIN_POINTS_PER_BIN` | 4; 1–1000 | Altera o percentil de seleção das cristas; não conta literalmente quatro pontos em cada vértice |
| `PLANNED_MAX_OFFSET` | 0,70; 0,20–1,50 m | Busca lateral do refinamento; limitada também pela entrelinha |
| `MIN_CROP_RUN` | 3; 0,5–10 m | Continuidade necessária para apoiar a centralização |
| `MIN_GAP_CM` | 50; mínimo 1 cm | Comprimento mínimo final para registrar falha |
| `REFINE_VISIBLE_GAPS` | Verdadeiro | Reconsidera ausências apoiadas por solo visível no RGB |
| `OUTPUT` | Obrigatório | Linhas com estatísticas |
| `OUTPUT_GAPS` | Opcional, criado por padrão | Segmentos que atingem o mínimo |
| `OUTPUT_REVIEW` | Opcional, não criado por padrão | Intervalos incertos e sem dados |

`MIN_GAP_CM` não controla se a geometria pode atravessar uma lacuna. `MAX_GAP` não é o mínimo agronômico de falha. Os parâmetros de afastamento e continuidade também participam do refinamento das referências extraídas automaticamente, apesar de seus rótulos mencionarem linhas projetadas.

## CRS e unidades

Na classificação, um CRS explícito precisa ser válido, projetado e métrico. Sem ele, a imagem mantém seu CRS quando já está em metros; caso contrário, `_local_utm_crs()` transforma o centro da extensão para WGS84 e calcula:

```text
zona = limitar(floor((longitude + 180) / 6) + 1, 1, 60)
EPSG = 32700 + zona, no hemisfério sul
EPSG = 32600 + zona, no hemisfério norte
```

A seleção automática exige longitude entre −180° e 180° e latitude entre −80° e 84°. Ela não escolhe automaticamente um código SIRGAS 2000. Um CRS métrico já existente, como o informado pelo usuário, é preservado quando não há substituição explícita.

Na restituição, o CRS de trabalho é o **CRS da nuvem**, que deve ser projetado em metros. A extensão do raster e, quando necessário, as linhas projetadas são transformadas para ele. A camada pontual não é reprojetada automaticamente por esse segundo algoritmo.

## Ordem das bandas entre etapas

A primeira ferramenta aceita R/G/B configuráveis e monta um VRT nessa ordem. O RGB gravado no modo de recorte segue essa preparação. Isso não modifica a ordem física do arquivo original.

Na restituição, a grade grosseira e o detector de centros leem as bandas físicas 1/2/3 como RGB. O amostrador final de falhas consulta os metadados de interpretação de cor e admite outra ordem física, usando 1/2/3 como fallback. Portanto, essas etapas não têm a mesma política de bandas. Um raster não convencional precisa ser preparado adequadamente para toda a restituição; selecionar bandas na primeira ferramenta não reconfigura a segunda automaticamente.
