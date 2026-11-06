# 06 — Restituição automática e uso de linhas projetadas

[Índice](README.md) · Fonte: [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py).

## Escolha do ramo

Com `INPUT_PLANNED_LINES` válido, a ferramenta parte das geometrias informadas. Sem ele, estima orientação e cristas na grade de fusão, rastreia essas cristas e usa os traçados como referências para o mesmo refinamento de centros.

Em ambos os ramos, os comprimentos de falha calculados durante o rastreamento são **provisórios**. `_remeasure_gaps()` substitui esses valores usando o raster de referência.

## Encontrar sementes automáticas

Em `_trace_rows_and_gaps()`:

- `has_veg = density > 0,1`;
- cobertura local usa filtro médio de aproximadamente 3 m, mínimo 5 células;
- `crop_dilated` usa filtro máximo 3 × 3 para tolerância geométrica;
- percentil-base é `clamp(15+2×MIN_POINTS_PER_BIN, 15, 40)`;
- limiar da crista é o maior entre 0,010 e esse percentil das respostas positivas;
- candidatos exigem resposta acima do limiar, cobertura > 0,02 e coerência > 0,09.

Os candidatos são comparados às duas vizinhanças na direção normal aproximada, conservando máximos. Uma parábola de três amostras fornece correção subpixel limitada a ±0,5 célula.

A seleção de sementes usa máximos das cristas, processados em faixas com halo de uma célula. Não exige que a crista coincida com uma grade fixa de três pixels. As sementes são ordenadas pela resposta, da maior para a menor.

## Avanço nas duas direções

O passo nominal é 0,60 m; em pixels, é pelo menos 2 células. A busca lateral por passo usa:

```text
máximo_lateral = min(0,38S, MAX_DEVIATION × passo_efetivo)
```

O algoritmo prevê o próximo ponto pela tangente, pesquisa offsets laterais discretos e escolhe a crista com melhor resposta penalizada pelo afastamento. Quando encontra crista, zera a contagem de passos sem apoio. Quando não encontra, admite passos fracos até o limite derivado de `MAX_GAP`.

O avanço para quando alcança a margem da grade, cobertura local < 0,015, coerência < 0,07, região já visitada, lacuna excessiva ou diferença angular local maior que 0,70 rad. A direção é atualizada com 40% da diferença angular aceita.

O caminho final combina avanço invertido, semente e avanço direto. Trechos curtos, com poucas ocorrências de cultura dilatada ou comprimento insuficiente são rejeitados. O traçado é aparado à primeira e à última ocorrência dessa cultura provisória.

## Supressão de duplicações e suavização

A vizinhança visitada é marcada ao longo do traçado bruto com raio em células derivado de `0,38S`. Isso reduz sementes concorrentes, mas não é uma prova topológica global de ausência de duplicações.

`_smooth_or_straighten_grid_line()`:

- se o desvio lateral máximo da corda é < 0,45 m, projeta os pontos na direção principal da covariância, produzindo uma reta;
- nos outros casos, com pelo menos cinco pontos, aplica suavização gaussiana e transição de três vértices nas extremidades.

As coordenadas da grade são convertidas ao mapa usando centros de células. O ângulo de saída é o da corda, módulo 180°; em uma curva ele não descreve cada tangente local.

## Referências informadas ou extraídas

`_extract_planned_polylines()` ignora geometrias vazias, transforma CRS quando necessário e extrai cada parte linear. Erros de transformação de uma feição fazem essa feição ser ignorada. A primeira seleção usa extensão retangular; o recorte pela validade nativa ocorre depois.

`_resample_and_smooth_planned_line()` remove segmentos de até `10⁻⁴ m`, recusa comprimento < 2 m, parametriza por distância e reamostra. O refinamento principal solicita aproximadamente 25 cm e `preserve_geometry=True`.

A função identifica tiro reto por desvio < 0,35 m; subtrechos podem ser considerados retos por desvio < 0,30 m. Isso escolhe a política de ajuste, sem necessariamente substituir a referência preservada por sua corda.

O modo opcional `preserve_geometry=False` permite retificar ou suavizar a referência; o caminho principal de refinamento usa a preservação. O sinal das normais é estabilizado pela orientação média, para que offsets laterais tenham convenção consistente.

## Refinamento comum

`_reconstruct_from_planned_lines()` reúne pontos, máscara raster e contraste em um sinal contínuo, pesquisa offsets laterais e associa núcleos RGB a uma única referência. A construção e os limites do ajuste estão no [guia 07](07_CENTROS_E_AJUSTE.md).

Sem projeto, os traçados refinados ainda passam por conexão de fragmentos, famílias de orientação, conclusão de rede e novo recorte pela imagem. Com projeto, as referências podem representar locais sem cultura, inclusive fileiras vazias; um registro comum só é transferido sob as condições do [guia 08](08_CONTINUIDADE_E_PROJECOES.md).
