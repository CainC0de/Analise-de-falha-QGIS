# 05 — Grade espacial, fusão e orientação local

[Índice](README.md) · Fonte: [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py), métodos de `_accumulate_points_grid()` a `_steerable_ridge_filter_tiled()`.

## Extensão e tamanho da grade

A área inicial é a interseção da extensão do raster transformada com a extensão da nuvem, combinada à extensão do projeto quando informado. Acrescenta-se margem `max(2 m, 2 × S)`, onde `S` é a entrelinha.

```text
com projeto: r = min(0,15; max(0,10; S/10)) m
sem projeto: r = min(0,20; max(0,10; S/8)) m
```

As dimensões têm mínimo de 16 células por eixo. Enquanto o produto ultrapassa 80 milhões de células, `r` é multiplicado por 1,15 e as dimensões são recalculadas. Essa é a grade geométrica; não redefine o mínimo de falha nem cria detalhe no raster original.

## Acumular pontos

`_accumulate_points_grid()` filtra as feições pela extensão retangular da imagem, sem atributos. Ignora geometrias vazias e coordenadas não finitas. Processa lotes de 100.000 pontos.

`_splat_points()` calcula `col=floor((X−xmin)/r)` e `row=floor((ymax−Y)/r)`, confere os limites e soma 1 com `np.add.at`. Essa filtragem retangular não é, sozinha, uma conferência de todos os buracos do raster.

Sem projeto, menos de dez pontos dentro da seleção impede continuar. Com projeto, a geometria externa permite trabalhar com apoio pontual insuficiente.

## Extrair sinal do raster

`_extract_raster_crop_grid()` monta um VRT alinhado exatamente à grade, reprojetado para o CRS dos pontos e reamostrado por **average**.

- RGB: lê bandas físicas 1/2/3, NoData e banda 4 quando presente; chama `_classify_rgb_grid()`.
- Uma banda: usa `banda==1` como cultura e `banda!=255` como validade. Só devolve densidade quando a fração de cultura válida é menor que 0,55; conserva a validade nos demais casos.
- Falha na extração: devolve `None` para os sinais indisponíveis; a fusão pode usar apenas pontos.

No RGB, o contraste usa GLI, NGRDI, fundo de aproximadamente 0,85 m e normalização ampla de aproximadamente 4,5 m. Os critérios locais de fileira são os mesmos limiares sem o ajuste `T` da primeira ferramenta. Nesta função, o núcleo denso usa apenas os índices amplos `GLI>0,085` e `NGRDI>−0,005`, sem a condição adicional de 60% de verde forte da geração de pontos.

São devolvidos `crop_grid`, contraste positivo e **validade original**. Excluir uma mancha como apoio vegetal não transforma seus pixels em buraco de cobertura para recortar linhas.

## Fusão

`pt_bin = densidade_pontos > 0`. Sem sinal raster utilizável, a fusão é `pt_bin`.

Com raster:

1. Expandir a ocupação pontual por filtro máximo de tamanho aproximado de 2,5 m, mínimo 5 células, criando um envelope de trabalho.
2. Medir a ocupação pontual média dentro desse envelope.
3. Se a ocupação for menor que 0,035 ou maior que 0,55, usar `raster_density × envelope`.
4. Caso contrário, usar `clip(0,55pt_bin + 0,45raster_density × envelope, 0, 1)`.

O envelope impede que o raster introduza apoio arbitrário em toda a imagem fora da vizinhança dos pontos. Seu tamanho de filtro não equivale a um raio de 2,5 m.

## Orientação pela FFT

Sem projeto, `_build_local_orientation_field()` trabalha em janelas de aproximadamente **16 m**, deslocadas aproximadamente **8 m**, com janela Hann. Rejeita patches cuja ocupação média não esteja entre 0,012 e 0,68.

1. Subtrair a média do patch e aplicar a janela Hann 2D.
2. Calcular potência `abs(rfft2(patch))²`.
3. Concentrar o peso próximo de `f0=1/S`, com largura gaussiana `0,22f0`, cortada fora de `0,55f0–1,50f0`.
4. A frequência identifica a normal da repetição; somar π/2 dá a tangente da fileira.
5. Acumular `cos(2θ)` e `sin(2θ)`. O ângulo duplo identifica como equivalentes θ e θ+π.
6. Calcular coerência direcional, penalizada quando a energia no anel é fraca em relação à banda `0,20f0–2f0`.
7. Conservar amostras com coerência > 0,12; suavizar os componentes e ampliar à grade completa.
8. Recuperar `θ = 0,5 atan2(v,u) mod π`.

A coerência mede organização do sinal nessa escala. Não identifica espécie nem garante orientação correta quando há repetição de solo, palhada ou carreadores.

## Filtro direcional

`_steerable_ridge_filter_tiled()` prepara 12 orientações em `[0,π)`. Para coordenadas rotacionadas longitudinal `t` e transversal `s`, o kernel combina:

```text
exp(−0,5(t/σlong)²)
× cos(2πsr/S)
× exp(−0,5(s/σtrans)²)
```

`σlong=2/r` células e `σtrans=0,65S/r`. A média do kernel é removida e sua soma absoluta normalizada. A convolução é feita por FFT em blocos internos de 1024 células com halo do kernel.

Somente regiões com coerência ≥ 0,08 são ativas. Cada célula recebe interpolação entre as duas orientações discretas vizinhas. O resultado é uma resposta de crista para iniciar o rastreamento, não uma máscara final de falhas.
