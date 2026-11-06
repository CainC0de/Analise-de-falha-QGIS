# 04 — Formação da nuvem de pontos da cultura

[Índice](README.md) · Fonte: [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py), `processAlgorithm()` após `_classify_window()`.

## O que cada ponto representa

A saída é vetorial **Point 2D**, no CRS métrico de saída. Cada ponto representa o centroide dos pixels aceitos em uma célula de agregação. Não há estimativa de altura, LAS/LAZ, triangulação fotogramétrica ou correspondência garantida de um ponto por touceira.

O apoio vem de `crop_point_mask`, que combina cor, contraste, verde suave próximo de um núcleo e exclusão de manchas densas. O GeoTIFF usa outra máscara: diferenças visuais entre raster e nuvem podem resultar dessa seleção deliberada.

## Espaçamento efetivo

Defina `p` como o menor lado métrico do pixel preparado e `d` como o espaçamento solicitado em metros:

```text
área_retangular = largura_px × largura_pixel × altura_px × altura_pixel
se área_retangular > 500.000 m² e d < 0,20 m: d_efetivo = 0,20 m
caso contrário: d_efetivo = d
stride = max(1, round(d_efetivo / p))
espaçamento_informado_no_log = stride × p
```

A área acima é a da grade retangular, não a área líquida do polígono. A agregação é por número inteiro de pixels; o espaçamento é aproximado e os centroides não formam necessariamente uma malha regular.

Há um comentário histórico sobre não tornar a nuvem mais grosseira que 30 cm, mas a fórmula atual **não aplica esse teto**. O diálogo aceita até 200 cm e a regra explícita adicional é o piso de 20 cm em grades grandes. A interpretação deve seguir a fórmula executada.

## Blocos e halo

O número de células por bloco é `max(16, round(2048/stride))`. O lado interno do bloco é esse valor multiplicado por `stride`; assim, cada célula de agregação fica contida em um bloco.

O halo é `max(16, ceil(4,5/p))` pixels. A classificação considera o bloco ampliado, mas só a área interna é gravada. O halo fornece vizinhança para as estatísticas locais e evita repetir a saída nas sobreposições.

## Seleção e cálculo dos centroides

Para cada bloco:

1. Localizar os índices de pixels `True` em `inner_crop`.
2. Converter cada pixel em identificador de célula por divisão inteira por `stride`.
3. Usar `unique` e `bincount` para contar e acumular linhas, colunas e GLI por célula.
4. Aceitar somente células com pelo menos `max(1, round(stride² × 0,34))` pixels de apoio.
5. Calcular média de linha, coluna e GLI usando os pixels aceitos, sem ponderação por intensidade.
6. Converter o centroide ao mapa e conferir a máscara poligonal, quando houver.
7. Criar a feição e inseri-la no sink.

O limiar de ocupação usa a área nominal da célula inteira, inclusive em células parciais na borda do bloco/imagem. Não é recalculado pelo número de pixels válidos dessa célula parcial.

## Coordenadas no centro dos pixels

Com linha média `r̄`, coluna média `c̄` e geotransform `gt`:

```text
X = gt[0] + (c̄ + 0,5)gt[1] + (r̄ + 0,5)gt[2]
Y = gt[3] + (c̄ + 0,5)gt[4] + (r̄ + 0,5)gt[5]
```

O `+0,5` distingue centro e canto do pixel. A transformação inclui rotação caso a grade recebida a conserve.

## Atributos e gravação

| Campo | Conteúdo |
| --- | --- |
| `gli` | Média do GLI dos pixels agregados |
| `classe` | Inteiro 1 para os pontos emitidos |
| `pixel_count` | Quantidade de pixels de apoio naquela célula |

As inserções são agrupadas em lotes de 10.000 feições, usando `FastInsert`. Erro na inserção interrompe o algoritmo. Blocos sem pixels válidos não geram pontos.

Na restituição atual, a acumulação da nuvem lê **geometrias sem atributos**. Ela conta cada feição como uma ocorrência na grade; `gli` e `pixel_count` não são usados como pesos e a restituição não refiltra o campo `classe`. A seleção de uma nuvem externa precisa, portanto, conter os pontos que se deseja tratar como apoio da cultura.
