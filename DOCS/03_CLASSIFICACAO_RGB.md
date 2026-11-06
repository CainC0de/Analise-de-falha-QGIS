# 03 — Identificação de cobertura verde no primeiro algoritmo

[Índice](README.md) · Fonte: [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py), `_classify_window()`.

Esta função devolve **três matrizes**: máscara de vegetação para o GeoTIFF, máscara de apoio para pontos e índice GLI. As duas máscaras são diferentes. A medição final de falhas usa outro classificador, descrito no [guia 09](09_IDENTIFICACAO_DE_FALHAS.md).

## Índices

As bandas são convertidas a `float32` antes da aritmética. Com denominadores acrescidos de `10⁻⁶`:

```text
GLI   = (2G − R − B) / (2G + R + B)
NGRDI = (G − R) / (G + R)
```

Denote por `T` o ajuste `GLI_THRESHOLD`.

| Sinal | Condições simultâneas, além da validade |
| --- | --- |
| `is_pure_green` | GLI > 0,08 + 0,5T; NGRDI > 0,01 + 0,5T; G > R; G > B |
| `is_soft_green` | GLI > 0,025 + 0,5T; NGRDI > −0,035 + 0,5T; G > B; G ≥ 0,97R |

Esses sinais representam respostas de cor, não identificação botânica da espécie.

## Fundo local adaptativo

Para reduzir o custo dos filtros, a função usa fator `max(1, round(0,15 / max(0,01, pixel_m)))`. Quando há pelo menos oito células reduzidas em cada dimensão, calcula médias por blocos desse fator, incluindo a fração válida. Caso contrário, trabalha na resolução recebida.

Em uma janela de aproximadamente 0,85 m, com tamanho ímpar mínimo 3, estima médias de GLI e NGRDI normalizadas pela validade. Define:

```text
ΔGLI = GLI − fundo_GLI
ΔNGRDI = NGRDI − fundo_NGRDI
C = 0,55ΔGLI + 0,45ΔNGRDI
```

Em janela de aproximadamente 4,5 m, mínimo 9 células, calcula a média local de `abs(C)` e os fundos amplos dos índices. A variável `mad` do código corresponde a essa média absoluta do contraste, não à mediana estatística dos desvios.

As estatísticas reduzidas são ampliadas à matriz original por interpolação de ordem 1. A máscara de mancha densa usa ordem 0.

## Sinal de fileira

`is_row_veg` exige todas as condições:

```text
C > max(0,0045; 0,55 × média_absoluta_local) + 0,20T
ΔGLI > 0,003
ΔNGRDI > 0,002
GLI > 0,005 + 0,5T
NGRDI > −0,085 + 0,5T
G > B
pixel válido
```

O objetivo do contraste é distinguir uma resposta vegetal local do fundo, como palhada amarela com GLI positivo. Ajustes positivos elevam os limiares; negativos os reduzem. Não há invariância matemática garantida a toda iluminação ou costura de voo.

## Exclusão de manchas densas na nuvem

Na grade de estatísticas, a fração de verde forte é suavizada na janela ampla. Um núcleo de mancha densa requer:

```text
GLI amplo > 0,085
NGRDI amplo > −0,005
cobertura de verde forte > 60%
```

O buffer lógico é obtido por filtro médio com tamanho aproximado de 7 m, mínimo 5 células, seguido de limiar > 0,10. Esse tamanho é a janela do filtro, não um raio de exclusão de 7 m.

A intenção é reduzir mata/APP e outras manchas contínuas na nuvem. Uma mancha de cana fechada ou invasoras pode ter a mesma aparência. O filtro não fornece um mapa certificado de mata ou espécies.

## Formação das duas máscaras

```text
vegetação_raster = is_row_veg OU is_pure_green
núcleo_pontos = is_row_veg OU is_pure_green
verde_suave_aceito = is_soft_green E proximidade de núcleo_pontos
apoio_pontos = (núcleo_pontos OU verde_suave_aceito) E NÃO buffer_denso
```

A proximidade usa `maximum_filter` de tamanho ímpar derivado de `max(3, round(0,30/pixel_m))`: é uma vizinhança quadrada em pixels, não uma distância euclidiana exata de 30 cm.

Quando o pixel é menor que 6 cm, há abertura binária 2 × 2 nas máscaras indicadas pelo código. Isso pode eliminar estruturas muito pequenas. O GeoTIFF usa a máscara de vegetação; a nuvem usa a máscara de pontos com suporte suave e exclusão de manchas densas.

## Interpretação

O valor raster 1 significa verde detectado; 0 significa ausência desse verde segundo esta classificação; 255 significa inválido. Uma região zero pode conter cana amarelada, sombra ou uma resposta não reconhecida. É por isso que a análise final de falhas deve preferir o RGB original e distinguir incerteza de ausência.
