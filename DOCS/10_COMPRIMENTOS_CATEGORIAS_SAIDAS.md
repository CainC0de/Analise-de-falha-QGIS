# 10 — Comprimentos, categorias, estatísticas e arquivos de saída

[Índice](README.md) · Fontes: [planting_gaps.py](../planting_gaps.py) e `_remeasure_gaps()` / gravação em [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py).

## Comprimento ao longo da linha

`sample_polyline()` remove segmentos quase nulos e calcula distâncias acumuladas pela soma euclidiana dos segmentos. Em curvas, usa o caminho da polilinha, não a distância direta entre suas extremidades.

As bordas das células de medição usam passos completos; somente a última célula recebe o restante. Dez células de 5 cm continuam somando 50 cm, em vez de encolherem porque toda a linha foi redistribuída por `linspace`. As observações RGB são tomadas nos centros dessas células.

## Formar intervalos

`intervals_from_states()` localiza mudanças de estado e aceita somente sequências de zero com:

```text
fim − início + 10⁻⁹ m ≥ mínimo_em_metros
```

A pequena parcela adicional é tolerância numérica, não redução agronômica do mínimo. A chamada final usa `min_crop_m=0`: plantas curtas confirmadas não são apagadas para unir ausências.

A função dispõe de opção genérica para remover presenças internas menores que `min_crop_m`, mas ela **não é ativada na medição final**. NoData e incerteza não são atravessados por essa opção.

Exemplo com mínimo de 50 cm:

| Sequência ao longo da linha | Resultado |
| --- | --- |
| 50 cm de ausência contínua | Um segmento elegível |
| 49 cm de ausência | Não atinge o mínimo |
| 40 cm de ausência, planta, 40 cm de ausência | Nenhum segmento de 80 cm |
| 80 cm de ausência, NoData, 90 cm de ausência | Duas ausências separadas |
| 80 cm de ausência, trecho incerto | Ausência limitada por incerteza; não inclui o trecho incerto |

## Categorias

| Categoria | Regra |
| --- | --- |
| `interna` | Não toca nenhuma extremidade da parte medida |
| `inicial` | Começa no início da parte |
| `final` | Termina no final da parte |
| `total` | Ocupa toda a parte medida |
| `limite_dados` | Tem estado −1 imediatamente antes ou depois |
| `limite_incerto` | Tem estado −2 imediatamente antes ou depois, sem prioridade de −1 |

As categorias de limite têm prioridade sobre a classificação inicial/final/interna/total quando se aplicam. Uma parte separada pelo recorte pode ter início próprio; os nomes se referem à parte medida, não necessariamente à fileira agronômica inteira.

`review_intervals()` emite intervalos −1 como `sem_dados` e −2 como `incerto`, sem usar o mínimo de falha. `segment_coordinates()` interpola as duas extremidades e conserva os vértices internos da linha.

## Estatísticas

```text
falha_m = soma dos intervalos zero que atingem o mínimo
sem_dados_m = soma das células −1
incerto_m = soma das células −2
comprimento_avaliado = comprimento_total − sem_dados_m − incerto_m
falha_pct = 100 × falha_m / max(10⁻⁹, comprimento_avaliado)
```

Ausências menores que o mínimo não somam em `falha_m`, mas continuam no comprimento avaliado. O percentual geral do log usa a soma dos comprimentos avaliados das partes, não a média simples dos percentuais das linhas.

Percentual zero com grande comprimento incerto ou sem dados não comprova plantio completo. A geometria pode atravessar essas regiões e ainda assim não haver observação suficiente para uma classificação.

## Saídas da primeira operação

**GeoTIFF:** uma banda Byte; 1 verde, 0 sem verde detectado, 255 NoData. Tem geotransform, CRS, tabela de cores e metadados `CLASS_0`, `CLASS_1`, `INDEX`, `GLI_THRESHOLD`, `PIXEL_SIZE_CM`.

**Pontos:** geometria Point; campos `gli`, `classe` e `pixel_count`, descritos no [guia 04](04_NUVEM_DE_PONTOS.md).

**RGB preparado:** somente no modo de recorte; conserva a imagem utilizada para classificar e permite reutilizá-la na restituição.

## Campos das linhas restituídas

| Campo | Tipo | Conteúdo |
| --- | --- | --- |
| `linha_id` | Inteiro | Identificador sequencial da parte de saída |
| `angulo_graus` | Real | Ângulo da corda, módulo 180° |
| `compr_m` | Real | Comprimento da polilinha |
| `falha_m` | Real | Soma de ausências elegíveis |
| `falha_pct` | Real | Percentual sobre comprimento avaliado |
| `num_falhas` | Inteiro | Quantidade de intervalos elegíveis |
| `pct_pes` | Real | Percentual geométrico com apoio aceito para centralização |
| `pct_proj` | Real | Percentual geométrico protegido na referência |
| `sem_dados_m` | Real | Comprimento não observado |
| `amostra_cm` | Real | Primeiro passo efetivo das bordas de medição, convertido a cm |
| `incerto_m` | Real | Comprimento com classe ambígua |
| `origem` | Texto | Construção geométrica, conforme guia 08 |

`pct_pes` não é porcentagem de pés detectados; `pct_proj` também pode existir no modo automático, cuja referência foi o traçado observado. Os dois não precisam somar 100%, pois há transições e regras distintas de segmento.

## Campos das falhas e da revisão

| Saída | Campos |
| --- | --- |
| Falhas, LineString | `falha_id`, `linha_id`, `compr_m`, `categoria`, `evidencia` |
| Revisão, LineString | `linha_id`, `compr_m`, `motivo` |

`evidencia=solo_e_nucleo` significa que a reconsideração por solo/núcleo contribuiu em alguma célula daquele intervalo. `ausencia_raster` identifica os demais. Não são probabilidades nem rótulos botânicos.

Os campos numéricos são arredondados para armazenamento/apresentação, em geral a duas casas; a geometria e o teste do mínimo usam os valores de cálculo. O `compr_m` de falhas é atributo arredondado, não a fonte usada para decidir se uma geometria limítrofe passa no mínimo.

As linhas são inseridas em lotes de 2.000 e falhas em lotes de 5.000. A revisão usa callback de gravação durante a medição. Todas as saídas vetoriais usam o CRS métrico dos pontos.
