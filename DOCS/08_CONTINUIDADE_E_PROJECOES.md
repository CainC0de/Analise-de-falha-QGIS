# 08 — Conexão, inferência, cabeceiras e registro do projeto

[Índice](README.md) · Fonte: [row_network.py](../row_network.py).

Estas operações modificam ou completam **geometria**. Nenhuma delas confirma presença de planta no intervalo inserido. A medição final permanece independente.

## Recorte pela validade nativa

`clip_native()` parametriza cada parte por distância (`stationing()`) e consulta a validade do amostrador. Usa passo `max(0,01, min(0,025, res/2))` m. Partes ou grupos válidos com menos de 2,5 m são descartados.

Nos limites entre válido e inválido, oito bisseções refinam a transição. Os segmentos são extraídos por `segment_coordinates()`. O retorno inclui o índice da parte de origem, para manter a proveniência após divisões.

A validade usa alpha da grade de medição, não a máscara de vegetação. Uma região sem cultura pode continuar dentro da linha. Um buraco de NoData pode dividir a geometria. A resolução de consulta tem piso de 1 cm; isso é uma política de busca, não criação de detalhe na fonte.

## Ligar fragmentos observados

`connect_observed_fragments()` só tenta ligação com pelo menos quatro partes disponíveis. Na chamada principal, o raio de busca é:

```text
min(60 m, max(12 m, 6 × MAX_GAP))
```

Para cada par de extremidades:

1. Orientar os fragmentos como saída de um e entrada do outro.
2. Estimar tangentes nos últimos/primeiros 2 m; exigir produto escalar ≥ 0,97.
3. Conferir avanço positivo e deslocamento lateral dentro do limite preliminar.
4. Buscar até 24 guias próximas do ponto médio.
5. Exigir guias monotônicas que ultrapassem ambas as pontas em pelo menos 50 cm.
6. Exigir offsets com o mesmo sinal nas pontas, diferença ≤ `0,20S`, múltiplos de 1–3 entrelinhas com resíduo ≤ `0,18S`.
7. Exigir pelo menos 60% de apoio observado no intervalo e apoio nas duas extremidades de cada guia.
8. Escolher a guia mais próxima de cada lado; verificar separação consistente e resíduo de posição das pontas ≤ `0,15S`.
9. Interpolar o caminho entre as guias e corrigir suavemente os resíduos das pontas.

Uma observação já existente sobre a faixa veta a ligação concorrente. Candidatos são priorizados por comprimento; cada extremidade aceita no máximo uma conexão e a união de componentes impede ciclos.

O resultado conserva o apoio das partes originais e atribui **peso zero** aos pontos internos da ponte. A origem passa a `observada_conectada`.

## Famílias de orientação

`complete_network()` agrupa cordas com produto escalar absoluto ≥ 0,985 contra todos os membros de uma família. É um agrupamento de compatibilidade angular, não uma segmentação botânica ou um cadastro de talhões.

Cada família passa por `_complete_parallel_network()`. Os resultados mantêm a ordem das partes observadas; novas fileiras vêm depois. Uma curva com retorno ou projeção longitudinal não monotônica não é forçada a um modelo unidimensional.

## Modelo compartilhado e cabeceiras

O modelo local usa uma tangente mediana. Limites comuns vêm dos quantis 15% das entradas e 85% das saídas, acrescidos de margem `max(0,60 m, 2res)`.

Com pelo menos três perfis, o modelo compartilhado exige offsets compatíveis com múltiplos da entrelinha, ao menos dez amostras apoiadas por perfil e pelo menos duas observações em mais de 60% da grade comum. A forma é a mediana das observações alinhadas. A continuação desse **modelo compartilhado** ainda admite ajuste quadrático nas bordas apoiadas; isso é diferente da extensão individual.

Cada parte é estendida por no máximo `min(MAX_GAP, 3S)` na chamada principal. A extensão individual usa tendência linear dos últimos 4 m, evitando amplificar ruído com polinômio quadrático. Onde o modelo compartilhado existe, ele pode corrigir regiões sem apoio com deslocamento limitado a `0,30S`.

Fragmentos não ligados na mesma faixa não podem prolongar-se um através do outro: quando suas extremidades estão próximas e com lateral compatível, cada lado é limitado à sua metade do intervalo, com separação adicional de 2,5 cm por lado.

## Inferir fileira interior ausente

Uma candidata exige vizinhas com sobreposição longitudinal ≥ `max(6 m, 60% do menor perfil)`, distância correspondente a 2–4 entrelinhas, resíduo e variação transversal ≤ `0,12S`.

As fileiras internas são interpoladas entre essas vizinhas. Não se extrapolam novas fileiras além das externas. Há verificações locais de duplicação e distância ao caminho existente.

Depois das famílias, uma verificação **global** confronta cada candidata com todas as observações completadas, inclusive as de outras orientações. Observações com poucos vértices são densificadas a até 20 cm antes da árvore espacial. Distância mínima menor que `0,30S` veta o caminho; candidatas já aceitas também entram no controle.

Essa verificação amostrada reduz conflitos; não é um teorema de impossibilidade de cruzamentos em todos os dados. A auditoria de geometrias continua necessária.

## Registro comum de referências vazias

`register_empty_rows()` é usado no ramo com projeto. Referências são densificadas em aproximadamente 25 cm. Para estimar uma translação comum, exige-se:

- pelo menos três referências;
- linhas apoiadas com `pct_pes ≥ 35%` e comprimento ≥ 6 m;
- amostras a menos de `0,25S` da referência e ao menos cinco amostras por contribuição;
- contribuições de pelo menos três referências independentes;
- percentil 80 do resíduo ≤ 4 cm;
- deslocamento comum entre 2 cm e `0,20S`.

A solução por mínimos quadrados usa as normais das referências. A translação só é aplicada a linhas com `pct_pes < 10%`, cuja origem muda para `projeto_registrado`.

## Proveniência

| Valor de `origem` | Interpretação |
| --- | --- |
| `projeto` | Referência externa refinada conforme apoio |
| `projeto_registrado` | Referência com translação comum transferida |
| `observada` | Traçado inicial obtido automaticamente |
| `observada_conectada` | Fragmentos unidos com duas guias observadas |
| `inferida_entre_vizinhas` | Fileira interior interpolada por regularidade geométrica |

Esses valores identificam a construção geométrica. Não são classes de cultivo ou níveis de confiança estatística.
