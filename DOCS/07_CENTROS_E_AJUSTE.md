# 07 — Núcleos visíveis, contexto e ajuste das linhas

[Índice](README.md) · Fontes: [cane_centers.py](../cane_centers.py) e `_reconstruct_from_planned_lines()` / `_offsets_from_plant_centers()` em [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py).

## O centro que se procura

O detector estima o núcleo visível da massa vegetal, favorecendo regiões espessas e convergência de folhas. Não mede diretamente a base dos colmos sob o dossel. A nuvem agregada da primeira ferramenta e esses candidatos de centro são produtos diferentes.

## Ler o RGB para centros

`detect_stool_centers()` usa blocos de 40 m, halo padrão de 0,8 m, aumentado para pelo menos três pixels, e resolução:

```text
res = max(0,005 m, max_res, resolução_nativa_estimada)
max_res padrão = 0,045 m
```

O nome `max_res` não implica forçar pixels mais finos que a fonte. A reprojeção por VRT é bilinear. As bandas físicas 1/2/3 são lidas; máscaras de banda, finitude e RGB não totalmente zero definem a validade. Blocos com menos de 2% de validade são ignorados.

Somente candidatos da área interna do bloco são devolvidos, evitando repetir os halos. `keep_fn` elimina centros distantes das referências. As coordenadas usam explicitamente centro de pixel.

## Pontuação de núcleo

`stool_center_score()` executa:

1. `ExG=(2G−R−B)/(R+G+B+0,001)` e suavização gaussiana de 0,7 pixel.
2. Limiar `max(0,02, Otsu)` sobre pixels válidos, salvo limiar explícito.
3. Abertura 2 × 2 da vegetação.
4. Abertura por disco com raio físico padrão de 7 cm.
5. Transformada de distância do núcleo, em metros, suavizada.
6. Densidade vegetal suavizada em escala de 10 cm.

`_otsu()` usa 128 bins entre percentis 1 e 99. Com menos de 100 amostras, usa mediana; sem amostras, zero. `_disk()` converte o raio em um disco discreto com mínimo de um pixel.

Com votos ativados, o tensor estrutural dos gradientes Sobel estima a direção longitudinal de cada folha. A direção é orientada para o aumento de densidade vegetal ampla. Pixels vegetais com coerência > 0,25 votam ao longo de raios até aproximadamente 40 cm; a acumulação é suavizada.

Cada sinal é normalizado pelo percentil 98 sobre a vegetação, limitado a `[0,1]`. O score principal é:

```text
score = núcleo_normalizado^1,5 × (0,75 + 0,25densidade_normalizada)
se não existe núcleo: score = 0,30densidade_normalizada
com votos: score *= (0,75 + 0,25votos_normalizados)
```

O núcleo domina; votos sozinhos não devem deslocar o centro para anéis na borda de uma touceira.

## Máximos e associação

`local_maxima_centers()` procura máximos em vizinhança derivada de distância mínima de 18 cm e score > 0,10. Um platô conectado gera um representante. O refinamento subpixel usa centroide ponderado do score em vizinhança de aproximadamente 6 cm.

A restituição associa cada candidato à referência amostrada mais próxima. O candidato precisa estar dentro do afastamento permitido e próximo longitudinalmente da estação. Assim, um mesmo candidato não alimenta duas fileiras concorrentes. A confiança é um peso do detector, não uma probabilidade calibrada de ser cana.

## Perfil lateral da referência

O sinal geométrico mistura densidade, pelo menos 75% do apoio raster quando disponível e contraste multiplicado por 18, limitado a 1. Após suavização de aproximadamente 22 cm, subtrai o fundo de aproximadamente 95 cm.

A referência tem passo aproximado de 25 cm. A busca lateral tem passo de 4 cm e limite `min(0,45S, max(0,20 m, afastamento))`. No modo automático, o afastamento passado também é limitado a `0,30S`.

Uma âncora regional em escala longitudinal de 6 m delimita o corredor. O pico fino é refinado por parábola. Presença exige pico acima de `max(0,015, 0,30 × percentil95)` e apoio da máscara geométrica. Alinhamento exige largura ≤ `0,65S` e pico ≥ 1,3 vezes a média do corredor.

Candidatos RGB com peso ≥ 0,10 e afastamento da âncora ≤ `0,25S` podem substituir a estimativa da grade. Desvios da mediana em ±3 m maiores que `max(0,12 m, 0,12S)` são rejeitados. Ainda assim, a continuidade contextual não pode ser ignorada.

## Proteção por contexto

`row_context_support()` usa janela de 8 m e exige ocupação ≥ 50% e ocupação alinhada ≥ 40%. Grupos de observações são separados por intervalos maiores que 75 cm.

Uma ilha cercada por ausências de pelo menos 1,5 m perde apoio geométrico. Nas extremidades exige-se ausência de pelo menos uma janela inteira, evitando invalidar uma fileira saudável por uma margem normal. Grupos não isolados precisam alcançar `MIN_CROP_RUN`.

Baixo apoio sustentado por pelo menos `max(2 m, MIN_CROP_RUN)` é protegido. Se não há apoio confiável, a referência inteira permanece protegida. Uma touceira verdadeira isolada também pode não orientar a geometria. Isso não a converte automaticamente em falha na medição RGB final.

## Ajuste contínuo com limites

Em tiro reto, estima-se uma tendência linear robusta: cinco reponderações de resíduos, com escala de 6 cm. A inclinação da tendência é limitada a ±0,02 m/m. A flexão adicional fica limitada a 8 cm e a inclinação total é controlada em torno de 3 cm/m. Em curvas, a referência permanece e o limite de inclinação do deslocamento é 4 cm/m. A curvatura do deslocamento é limitada a 0,02 m⁻¹.

`fit_center_offsets()` resolve um ajuste ponderado com penalização:

```text
erro das observações
+ 0,02 ||flexão||²
+ 0,10 ||D1 flexão||²
+ 0,30 ||D2 flexão||²
```

As diferenças `D1` e `D2` usam o passo em metros. Um esquema ADMM aplica limites de amplitude e derivadas, com sistemas esparsos fatorados, três rodadas robustas e critério numérico de parada. Os limites dizem respeito ao deslocamento em relação à referência, não à curvatura absoluta de toda curva de nível.

Nos trechos protegidos, as incógnitas fixas são eliminadas do sistema para obter deslocamento total exatamente zero. A correção volta à referência de forma contínua. Salvaguardas de escala mantêm a solução viável se o orçamento de iterações acabar. Não se recorta depois a linha por uma máscara binária de vegetação, pois isso criaria quinas e descontinuidades.
