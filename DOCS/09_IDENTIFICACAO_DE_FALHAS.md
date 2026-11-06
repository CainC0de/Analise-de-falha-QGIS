# 09 — Como o raster vira presença, ausência ou revisão

[Índice](README.md) · Fonte: [planting_gaps.py](../planting_gaps.py), `GapRasterSampler`, `classify_cross_sections()`, `plant_body_pixels()`, `visible_soil_support()` e `bounded_visible_absence()`.

## Estados da medição

| Estado interno | Significado | Entra como falha? |
| --- | --- | --- |
| `1` | Presença vegetal apoiada pelos critérios do perfil | Não; interrompe ausência |
| `0` | Ausência apoiada pelas observações | Somente se o intervalo atingir o mínimo |
| `−1` | Dados indisponíveis/validade insuficiente | Não |
| `−2` | Evidência ambígua | Não |

Esses códigos não são os valores 0/1/255 do GeoTIFF da primeira operação. O classificador de falhas reconhece evidências de oliva/amarelecimento que a máscara binária já não conserva.

## Preparar a grade de medição

`GapRasterSampler.__init__()` abre a imagem e estima sua resolução no CRS de trabalho. Usa `max(0,01 m, lados da resolução reprojetada)` e monta um VRT métrico com alpha de destino. O reamostrador do VRT é bilinear para RGB e vizinho mais próximo para classificação.

Na grade desse VRT, `_native_sample()` consulta o pixel contendo cada coordenada por `floor`, sem uma segunda interpolação entre pixels do perfil. Portanto, “amostragem nativa” significa leitura discreta dessa grade efetiva; se houve reprojeção, ela já passou pelo Warp.

O RGB final respeita metadados `RedBand`, `GreenBand` e `BlueBand`; na falta deles usa bandas 1/2/3. Alpha e limites da grade determinam disponibilidade. A leitura é agrupada em tiles 256 × 256 com cache LRU de 32 MiB.

## Estações e faixas transversais

Na chamada de `_remeasure_gaps()`:

```text
passo_longitudinal = max(resolução_efetiva, min(0,05 m, mínimo_falha/4))
```

Cada estação tem centro e normal da linha. As seções atravessam de `−0,45S` a `+0,45S`. O número de amostras é ímpar, no mínimo 15, e inclui `N+1` posições para `N` intervalos, mantendo o passo transversal no máximo na resolução efetiva.

O classificador usa três faixas principais:

| Faixa | Limite lateral |
| --- | --- |
| Presença geral | `abs(offset) ≤ min(0,35 m, 0,28S)` |
| Fundo de entrelinha | `abs(offset) ≥ 0,35S`, dentro da seção lida |
| Proteção de núcleos deslocados | `abs(offset) ≤ min(0,50 m, 0,35S)` |

Cada bloco computacional tem até 512 estações no refinamento RGB, ou 256 no outro caminho, com halo físico suficiente para o contexto. A decisão de ausência visível é repetida depois no perfil inteiro, para não exigir que as duas pontas de uma falha longa estejam no mesmo bloco.

## Índices e comparação com o fundo

RGB é promovido para ponto flutuante antes dos produtos. Pixels precisam ser finitos, não negativos e ter soma > `10⁻⁶`.

```text
L = R + G + B
E = (2G − R − B) / L
N = (G − R) / (G + R)
V = (G² − R×B) / (G² + R×B)       [RGBVI]
Bf = B / L
```

Os denominadores recebem estabilização numérica no código. Para cada seção, `bg()` é a mediana dos pixels válidos das faixas de fundo. Definem-se `de=E−bg(E)`, `dn=N−bg(N)`, `dv=V−bg(V)` e `db=bg(Bf)−Bf`.

## Sementes de presença

Cada linha da tabela é uma conjunção; o conjunto de sementes é a união das quatro primeiras linhas, limitada à validade:

| Evidência | Condições |
| --- | --- |
| Verde absoluto | `E>0,10`, `N>0,025`, `G>B` |
| Verde relativo | `E>0,08`, `N>−0,02`, `de>0,045`, `dn>0,015`, `G>1,04B`, `L<0,85bg(L)` |
| Oliva | `E>0,045`, `N>−0,075`, `de>0,022`, `dn>0,003`, `G>1,04B`, `L<0,78bg(L)` |
| Amarelo-verde | `E>0,08`, `N>−0,06`, `V>0,18`, `dv>0,08`, `db>0,025`, `dn>−0,015`, `G>1,18B` |
| Amarelecimento ambíguo | `E>0,04`, `N>−0,16`, `V>0,10`, `dv>0,06`, `db>0,025`, `G>1,12B` |

A última linha gera apoio fraco/revisão, sem confirmar presença por si só. Os limiares são heurísticas desta implementação, não diagnóstico de clorose.

## Objetos conectados e largura

A máscara fraca reúne sementes, amarelecimento ambíguo e pixels com `de>0,012`, `dn>0`, `G>B`, `E>0,02` e `N>−0,085`.

Os componentes conectados são rotulados com vizinhança 3 × 3. Uma semente precisa ocupar pelo menos **0,003 m² dentro da faixa da própria fileira**, e o objeto pelo menos **0,01 m²**. A expansão fraca fica a até 20 cm de uma semente dessa faixa. Isso limita o crescimento sobre palhada conectada.

Por objeto e estação, mede-se a maior sequência transversal contígua. `local_positive_quantile()` estima o percentil 80 das larguras positivas em janela física de 1 m. A largura necessária é:

```text
max(min(0,06 m, 0,04S), min(0,15 m, metade_da_largura_típica_local))
```

Somar pixels dispersos não substitui essa sequência contígua. O uso de janela física local reduz dependência da divisão dos blocos.

## Sombra e folhagem não confirmada

Objetos ambíguos exigem área ≥ 0,025 m². Além da evidência de amarelecimento, entram respostas fracas mais escuras que `0,90bg(L)` e folhagem clara coerente com `E>0,055`, `V>0,12`, `dv>0,05`, `db>0,015` e `dn>0,005`.

Objetos escuros com `L<0,65bg(L)` e área ≥ 0,01 m² também podem impedir confirmação de ausência. Uma sombra coerente não é automaticamente tratada como solo.

O estado inicial é −1 se há menos de 75% de validade na faixa interna, com mínimo de duas amostras. Caso contrário: presença apoiada tem prioridade; objetos ambíguos ou menos de duas amostras de fundo produzem −2; o restante começa em zero.

## Solo visível e núcleos compactos

Um pixel de solo candidato precisa ser válido, não ser semente/amarelecimento ambíguo, ter `L>0,70bg(L)` e satisfazer:

```text
(de<0,035 E dn<0,015) OU (V<0,09 E N<0,01)
```

Quando passos longitudinal e transversal são de até 6 cm, procura-se também apoio de sementes na faixa ampliada. `plant_body_pixels()`:

1. Retira o solo do material vegetal.
2. Fecha pequenos vazios com disco de 3,5 cm.
3. Calcula distância métrica ao fundo.
4. Conserva núcleos com raio ≥ `max(5,5 cm, passos)` e distância ≥ 75% do máximo local em janela aproximada de 50 × 30 cm.
5. Recorta os núcleos à faixa permitida **antes** da dilatação.
6. Expande o núcleo pelo mesmo raio, respeitando validade.
7. Protege também componentes pequenos compactos: razão de lados ≤ 4, área ≥ 0,01 m² e ocupação ≥ 35% do retângulo. A proteção complementar fica perto da mediana longitudinal do objeto, com alcance entre 5 e 10 cm; o centro transversal precisa pertencer à faixa.

Um núcleo na faixa lateral adicional pode confirmar presença onde o corredor antigo de 35 cm não alcançava. A expansão de uma copa externa, sem núcleo pertencente à faixa, não basta.

## Reconsiderar ausência entre corpos vegetais

`visible_soil_support()` exige, na faixa central de até `min(10 cm, 0,09S)` para cada lado:

- pelo menos 90% de validade e duas amostras;
- pelo menos 80% de solo entre as amostras válidas;
- ausência de ocupação por sementes em mais de 25% da faixa central;
- nenhum corpo vegetal protegido na faixa ampliada.

`bounded_visible_absence()` só reconsidera estados inicialmente presentes ou ambíguos que satisfaçam essas condições. O intervalo precisa de corpo vegetal próximo nas duas pontas, a até 30 cm. Uma fronteira adjacente de dados ausentes pode substituir **uma** dessas pontas, mas ao menos um lado precisa de corpo observado.

Não existe o teto antigo de 3 m. NoData não é preenchido e separa os intervalos. Uma faixa verde fina indefinida, sem apoio nas pontas, não vira automaticamente uma falha total.

Em borda oblíqua, uma exceção permite medir solo no eixo mesmo com validade lateral insuficiente: pixels axiais válidos, pelo menos duas amostras centrais, ≥80% de solo central, fundo disponível e nenhuma planta observada. Um buraco no próprio eixo continua indisponível.

## Entrada binária e opção de refinamento

Com uma banda, somente valores 0/1 e alpha válida entram na medição. Presença é qualquer pixel 1 na faixa interna; falta de validade gera −1. Cor oliva, amarelecimento e morfologia RGB não podem ser recuperados dessa entrada.

Desativar `REFINE_VISIBLE_GAPS` desativa a reconsideração por solo entre núcleos. As proteções de presença lateral compacta e de evidência clara pertencem ao classificador-base RGB atual; essa opção não reverte todo o módulo para uma versão histórica.

Os próximos passos — mínimo, intervalos e percentuais — estão no [guia 10](10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md).
