# Falha de Plantio para QGIS (v2.3)

Plugin para o QGIS voltado à **análise automatizada de falhas de plantio na cultura de cana-de-açúcar** a partir de ortomosaicos RGB de drones/VANTs.

## Navegação

- [Visão geral](#visão-geral)
- [Classificar vegetação verde](#1-classificar-vegetação-verde-rgb)
- [Restituir linhas de plantio](#2-restituir-linhas-de-plantio-a-partir-dos-pontos)
- [Referências metodológicas](#referências-metodológicas)
- [Instalação e requisitos](#instalação-e-requisitos)

## Visão geral

O fluxo do plugin é composto por duas ferramentas principais na Caixa de Ferramentas de Processamento (**Falha de Plantio (Cana-de-açúcar) → Análise de falhas**):

1. **Classificar vegetação verde (RGB)** (`falhadeplantio:classificar_vegetacao_rgb`)
2. **Restituir linhas de plantio a partir dos pontos** (`falhadeplantio:restituir_linhas_plantio`)

---

## 1. Classificar vegetação verde (RGB)

Classifica a cobertura vegetal da cana-de-açúcar em imagens RGB e gera simultaneamente um raster temático (GeoTIFF) e uma nuvem de pontos representativa das touceiras/fileiras da cultura (GeoPackage).

### Escolha como preparar a imagem

O campo **Preparação da imagem** oferece dois modos:

1. **Usar o raster diretamente (sem recorte)**: selecione o RGB e execute como antes. A máscara é dispensada.
2. **Recortar pelo polígono do talhão e processar**: selecione o RGB, informe a camada poligonal em **Polígono do talhão** e escolha o **CRS de saída**, se desejar. O algoritmo recorta a imagem, reprojeta, classifica e gera a nuvem de pontos na mesma execução.

O CRS de saída deve ser **projetado em metros**, pois a resolução é informada em centímetros. Se deixar o CRS vazio, o plugin mantém o CRS métrico da imagem ou escolhe a zona UTM local automaticamente. O campo de CRS também pode ser usado no modo direto para reprojetar a classificação e os pontos.

No modo de recorte, há uma terceira saída: **Imagem RGB recortada e reprojetada**. Escolha um GeoTIFF de destino ou deixe o caminho vazio para gerar um temporário. Essa imagem é usada imediatamente como entrada da classificação e da nuvem e fica disponível para a restituição das linhas. Ao executar pela interface com carregamento de resultados, o RGB gerado automaticamente também é carregado no mapa.

Polígonos em outro CRS são transformados automaticamente. O recorte respeita partes separadas e buracos do polígono: o exterior fica transparente no RGB, com NoData na classificação, e os centroides dos pontos são conferidos contra a máscara. A imagem original é preservada. Máscaras vazias, inválidas ou sem interseção com a imagem são recusadas com uma mensagem explicativa.

### Metodologia de Classificação (v2.3)

Em lavouras de cana-de-açúcar, o solo frequentemente está coberto por **palhada seca** (de coloração amarelada/bege, onde $R > G \gg B$) e sujeito a **sombras de nuvens** e variações radiométricas entre faixas de voo. O uso isolado do índice GLI com limiar fixo (`GLI > 0`) classifica erroneamente a palhada como vegetação verde, pois o baixo valor da banda Azul ($B$) torna $2G - R - B > 0$.

Para resolver esse problema de forma robusta, o algoritmo combina:

1. **Índices Espectrais Complementares ($\text{GLI}$ + $\text{NGRDI}$)**:
   $$\text{GLI} = \frac{2G - R - B}{2G + R + B}, \qquad \text{NGRDI} = \frac{G - R}{G + R}$$
   Enquanto o $\text{GLI}$ destaca o excesso de verde em relação ao vermelho e azul, o $\text{NGRDI}$ penaliza diretamente a palhada amarela e o solo exposto avermelhado ($R > G$).
2. **Contraste Espacial Local Adaptativo (Filtro Top-Hat / Passa-Alta em janela de ~0,85 m)**:
   - Como as linhas de cana possuem ~0,25–0,45 m de largura intercaladas por entrelinhas de ~1,1–1,5 m de palhada/solo, uma janela móvel de ~0,85 m abrange sempre linha e entrelinha simultaneamente.
   - O algoritmo avalia o ganho local $\Delta\text{GLI}$ e $\Delta\text{NGRDI}$ em relação à vizinhança imediata e normaliza pelo desvio absoluto médio local (janela de 4,5 m). Isso garante **invariância a sombras de nuvens e costuras do ortomosaico**.
3. **Supressão Automática de Mata/APP e Bordas Transparentes**:
   - Reconhece automaticamente a banda `Alpha` (ou pixels de borda `(0,0,0)`) como `NoData (255)`.
   - Na geração da **nuvem de pontos da cultura**, filtra manchas extensas e contínuas de dossel arbóreo (mata nativa / APP) e estradas/carreadores, concentrando os pontos exclusivamente sobre as fileiras de plantio.
   - **Detecção Completa de Touceiras**: além do contraste local, detecta vegetação densa ou sombreada conectada ao núcleo verde da fileira, garantindo que mesmo touceiras com menor contraste radiométrico gerem pontos (cobertura de 99,2% da cana real nos testes de validação).
4. **Processamento em Blocos via VRT Dinâmico**:
   - A leitura e eventual reprojeção para UTM ocorrem sob demanda em memória via `GDAL VRT`, sem gravar arquivos temporários gigantescos em disco e mantendo a resolução espacial efetiva da imagem.

### Parâmetros de Entrada e Saída

- **Raster de entrada (imagem RGB)**: Ortomosaico RGB (com ou sem banda Alpha). Se estiver em coordenadas geográficas (graus), é reprojetado automaticamente para a zona UTM métrica local.
- **Preparação da imagem**: uso direto (padrão) ou recorte por polígono do talhão.
- **Polígono do talhão**: camada poligonal obrigatória apenas no modo de recorte; aceita camadas temporárias e arquivos.
- **CRS de saída**: opcional, projetado em metros; aplica-se à imagem preparada, à classificação e à nuvem.
- **Bandas R, G e B**: Índices das bandas vermelha, verde e azul (padrão: `1`, `2`, `3`).
- **Tamanho do pixel de saída (cm)**: Resolução desejada para o GeoTIFF classificado (padrão: `5,0 cm`; preserva a resolução nativa caso o raster original seja mais grosseiro, evitando superamostragem artificial).
- **Espaçamento aproximado entre pontos da nuvem (cm)**: Tamanho da célula espacial usada para agregar pixels de cultura em um ponto centroide representativo (padrão: `20,0 cm`).
- **Ajuste fino de sensibilidade GLI**: Valor de calibração fina sobre o limiar adaptativo automático (padrão: `0,0`; valores positivos tornam a detecção mais restritiva e valores negativos mais permissiva).
- **Saídas**:
  - **Classificação de vegetação (GeoTIFF)**: `1` = vegetação verde (verde), `0` = palhada/solo sem vegetação (vermelho), `255` = NoData (transparente).
  - **Nuvem de pontos da cultura (GeoPackage)**: Camada vetorial `Point` contendo os atributos `gli` (GLI médio na célula), `classe` (`1`) e `pixel_count` (quantidade de pixels verdes agregados).
  - **Imagem RGB recortada e reprojetada (GeoTIFF)**: gerada somente no modo de recorte; temporária ou salva no destino escolhido.

---

## 2. Restituir linhas de plantio a partir dos pontos

Reconstrói o traçado vetorial contínuo de cada linha de plantio — acompanhando **linhas retas, curvas de nível, terraços embutidos e múltiplos talhões com orientações distintas** — e quantifica as **falhas de plantio** ao longo de cada fileira.

### Linhas projetadas (opcional): regra de uso

O refinamento usa as linhas projetadas, quando disponíveis, ou as fileiras detectadas automaticamente como referência:

- **Centro estimado da touceira:** o RGB original é analisado em blocos com halo, sem criar resolução artificial. Abertura morfológica e transformada de distância priorizam o núcleo compacto; convergência de folhas fornece evidência complementar. Cada candidato pertence a uma única fileira de referência.
- **Pequenos desvios suaves:** a reta robusta recebe uma correção contínua de até 8 cm, com inclinação total de até 3 cm/m e curvatura adicional de até 0,02 m⁻¹. O ajuste ponderado penaliza curvatura e reduz o peso de observações discrepantes. Candidatos que exigem ultrapassar esses limites não são seguidos exatamente.
- **Curvas de nível:** a geometria de referência é preservada; a correção lateral tem inclinação máxima de 4 cm/m e curvatura adicional de até 0,02 m⁻¹.
- **Falhas:** observações ausentes recebem peso zero e o ajuste permanece contínuo. O traçado interpolado não é considerado prova de presença de cana; as falhas continuam sendo medidas pela cobertura vegetal.
- **Sem linhas projetadas:** as linhas detectadas automaticamente passam pelo mesmo refinamento de centros.
- **Raster sem RGB:** o algoritmo informa no log que usará a nuvem e a grade de cultura, com menor capacidade de localizar touceiras individuais.

Os parâmetros de afastamento lateral e comprimento mínimo de suporte contínuo permanecem disponíveis. A confiança do núcleo RGB não contorna mais o requisito de continuidade. O campo **pct_pes** indica o percentual de segmentos com suporte aceito nas duas extremidades.

#### Proteção de manchas verdes cercadas por falhas

O algoritmo avalia o contexto longitudinal e o perfil transversal antes de permitir que uma mancha verde desloque a linha:

- Em uma janela de 8 m, exige pelo menos 50% de ocupação vegetal e 40% de apoio com perfil de fileira. Perfis largos ou sem pico transversal destacado não orientam o traçado.
- Manchas separadas dos demais trechos por lacunas de pelo menos 1,5 m dos dois lados são rejeitadas como guia geométrico, mesmo com núcleos RGB fortes. Nas extremidades da imagem, exige 8 m de vazio observado para não confundir margens normais de cabeceira com isolamento.
- Regiões com apoio insuficiente durante pelo menos o maior valor entre 2 m e o comprimento mínimo configurado (padrão: 3 m) também são protegidas. Pequenos intervalos normais entre touceiras continuam interpoláveis.
- Nos trechos protegidos, o deslocamento é exatamente zero nos vértices amostrados: usa-se a geometria projetada, inclusive suas curvas. Nas bordas, o ajuste respeita os limites de inclinação e curvatura. Sem projeto informado, usa-se a fileira detectada como referência, sem inventar um projeto ausente.
- O campo **pct_proj** registra o percentual do comprimento mantido na referência por essa proteção; o log informa o comprimento total protegido.

Esses critérios são regras conservadoras deste projeto, não um classificador botânico validado. Uma touceira verdadeira isolada também deixa de orientar a linha, conforme a regra de uso. Vegetação ambígua não é automaticamente convertida em falha: os comprimentos de falha continuam derivados da cobertura vegetal. O bloqueio geométrico e a identificação de invasoras são decisões distintas.

**Limites da interpretação:** o centro do núcleo visível é uma estimativa, não uma medição da base dos colmos. Folhas sobrepostas, plantas daninhas, sombras e resolução insuficiente podem ocultar a base. Os limites geométricos reduzem ondulações, mas não garantem acerto de todos os pés.

**Validação desta revisão:** testes numéricos e imagens sintéticas verificam deslocamentos pequenos, observações discrepantes, lacunas, limites geométricos, coordenadas no centro do pixel e folhas assimétricas. As métricas de talhão registradas em revisões anteriores não validam este novo método. A validação com centros anotados no ortomosaico real ainda é necessária.

### Metodologia de Restituição e Análise de Falhas (v2.3)

Em vez de assumir um único ângulo global reto para toda a propriedade, o algoritmo executa um pipeline espacial 2D em quatro etapas:

1. **Grade Métrica de Fusão (Pontos + Contraste da Imagem)**:
   - Acumula a nuvem de pontos da cultura em uma grade métrica de alta resolução (~10–20 cm) e combina com o sinal de contraste das fileiras extraído da imagem de referência. Caso a nuvem de pontos de entrada tenha sido gerada com espaçamento grosseiro ou limiar inadequado, o algoritmo recupera automaticamente o alinhamento fino das fileiras a partir do raster dentro do envelope dos pontos.
2. **Campo 2D de Orientação Local via FFT em Janelas (`2D Windowed Fourier Transform`)**:
   - Calcula o espectro de potência 2D em janelas deslizantes (16 m × 16 m) e analisa a energia concentrada no anel de frequência fundamental do espaçamento entre linhas ($f_0 = 1 / S$).
   - Constrói um campo vetorial suave de orientação tangente $\theta(y, x)$ e coerência periódica $C(y, x)$ por meio de suavização no espaço de ângulo duplo ($\cos 2\theta, \sin 2\theta$). Isso permite seguir **curvas de nível acentuadas** e transições entre talhões, enquanto regiões sem periodicidade de fileiras (carreadores, áreas vazias e matas) recebem coerência nula.
3. **Banco de Filtros Direcionais Guiados (`Steerable Comb Ridge Filter`)**:
   - Aplica um banco de filtros direcionais (suavização longitudinal ao longo da fileira combinada com perfil transversal cosseno-gaussiano sintonizado no espaçamento $S$) apenas nos canais angulares ativos de cada bloco.
   - Os lóbulos negativos em $\pm S/2$ suprimem plantas daninhas na entrelinha, enquanto o suporte longitudinal e os harmônicos em $\pm S$ interpolam suavemente o centro da fileira através das falhas de plantio seguindo a curvatura das linhas vizinhas.
4. **Rastreamento Sub-pixel de Cristas e Medição de Falhas**:
   - Extrai as cristas máximas na direção normal local com interpolação parabólica sub-pixel e rastreia cada fileira continuamente sem descontinuidade em $0^\circ / 180^\circ$.
   - A medição final é independente do traçado: amostra o raster original sem dilatação em uma faixa estreita central, evitando preencher falhas com folhas laterais ou vegetação de fileiras vizinhas. A geometria restituída é preservada.

### Medição e categorização das falhas

- **Tamanho mínimo para identificação como falha (cm)**: padrão **50 cm**; por exemplo, 100 considera somente trechos com pelo menos 1 m. O valor não altera a restituição nem o parâmetro de interpolação longitudinal.
- A amostragem acompanha a distância ao longo das curvas, com passo de até 5 cm quando a resolução permite. Não se inventa resolução: pixels mais grosseiros limitam o detalhe, e mínimos inferiores a dois pixels geram aviso.
- O perfil transversal avalia a faixa da fileira até 35 cm de cada lado do eixo, limitada a 28% do espaçamento. Amostras externas, ainda dentro de meia entrelinha, estimam a cor local do solo. A comparação de cromaticidade com esse fundo permite reconhecer cana oliva/amarelada sem exigir que o verde seja maior que o vermelho.
- Os intervalos usam passos completos (por exemplo, 5 cm), deixando somente a última célula com o restante do comprimento. Isso evita descartar uma falha no limite de 50 cm porque a divisão uniforme da linha produziu dez células ligeiramente menores que 5 cm.
- O apoio transversal de cada objeto confirma presença em qualquer posição da faixa; a planta não precisa cair exatamente no eixo. Evidência fraca, sombra ou falta de fundo comparável é marcada como **incerta**, em vez de ser convertida diretamente em ausência.
- Presença confirmada, mesmo em um trecho longitudinal curto, interrompe a falha. A medição final não apaga plantas com um filtro de comprimento nem junta ausências através de plantas ou regiões incertas. A detecção geométrica de fileiras e sua proteção contra manchas isoladas continuam independentes dessa medição.
- A confirmação usa objetos conectados no perfil da fileira: sementes de cor vegetal e contraste são expandidas somente sobre evidência fraca conectada e até 20 cm da semente. O núcleo deve ter pelo menos 0,003 m² de amostras e o objeto 0,01 m². Isso impede que uma touceira confirme um tapete inteiro de palhada conectado por variações de cor.
- A semente precisa estar dentro da faixa da própria fileira. A largura mínima contígua parte de 4% do espaçamento, limitada a 6 cm, e se adapta à metade da largura típica de cada objeto, até 15 cm. Isso reduz a influência de bordas parciais e pontas de folhas sem impor a largura de uma touceira grande às pequenas isoladas. Objetos escuros sem confirmação suficiente ainda podem permanecer incertos.
- Na medição, o RGB e a máscara de validade são amostrados no pixel nativo mais próximo. Evita-se a mistura bilinear de folhas com solo que expandia a presença vegetal e eliminava falhas próximas do mínimo. O mínimo configurado não é reduzido. A reprojeção, quando necessária, continua sujeita ao detalhe disponível na imagem.
- Para cana moderadamente amarelada e clara, o perfil combina RGBVI `(G² − R×B)/(G² + R×B)`, proporção de azul e contraste com a entrelinha, sem exigir que G seja maior que R nem que a planta seja escura. Amarelecimento forte com contraste coerente, mas sem confirmação suficiente, gera revisão em vez de uma falha automática. Palhada amarela uniforme não confirma cultura apenas pela cor. Esses critérios são heurísticos, não um diagnóstico de clorose nem uma classificação botânica.
- A medição respeita os metadados das bandas vermelha, verde e azul do TIFF; sem esses metadados, usa as bandas 1, 2 e 3 nessa ordem. Para avaliar cana amarelada, informe o **RGB original como imagem de referência**: uma máscara binária já perdeu essa informação de cor e não permite recuperá-la.
- Variações fracas e dispersas de palhada não reiniciam o contador de ausência. Sombras coerentes e objetos ambíguos com apoio espacial suficiente continuam incertos; não se unem falhas através deles. A decisão considera áreas físicas, com vizinhança adicional entre blocos para reduzir efeitos das emendas de processamento.
- Os limites são medidos pelas bordas das células de amostragem. Os segmentos não incorporam o vértice vizinho com cultura, evitando o alongamento artificial da medição antiga.
- Categorias: **interna**, **inicial**, **final**, **total**, **limite_dados** (adjacente a NoData) e **limite_incerto** (adjacente a evidência ambígua). Falhas limitadas por regiões não avaliadas podem continuar além do trecho confirmado.
- NoData/transparência é registrado em `sem_dados_m` e ambiguidade em `incerto_m`. Ambos são excluídos do denominador de `falha_pct`. Percentual zero com grande comprimento incerto não significa comprovação de plantio completo; esses trechos exigem revisão.

O RGB indica cobertura vegetal visível, não a existência de colmos sob folhas sobrepostas. Dossel fechado e invasoras podem ocultar falhas. A escolha de uma época com menor fechamento de dossel e a conferência com medições de campo continuam necessárias. A regra de 50 cm é um padrão histórico, e o usuário pode alterá-la.

A máscara de cobertura válida do raster é separada da classificação de vegetação. Rejeitar uma área densa como guia de cultura não remove a geometria de uma linha projetada dentro da imagem. Partes projetadas só são recortadas por limites/NoData da imagem, mantendo os filtros mínimos de comprimento da restituição.

### Continuidade e origem das linhas (2.4)

- O recorte da geometria usa a cobertura válida nativa do raster e refina as transições junto às bordas, evitando terminar uma linha no vértice anterior da grade de 25 cm.
- No modo automático, primeiro são refinadas as fileiras observadas. Um modelo comum de curvatura usa somente apoio de cultura aceito para melhorar trechos protegidos e as extremidades, com extensão limitada e recorte pela imagem. A inferência de fileiras vazias é restrita ao interior de vizinhas paralelas, com espaçamento regular, sobreposição longitudinal suficiente e controle de duplicações. Não são criadas novas fileiras além das externas observadas.
- Um projeto deslocado pode transferir seu registro às fileiras sem apoio próprio somente quando pelo menos três fileiras com cultura apresentam deslocamento pequeno e coerente. Uma mancha isolada não fornece esse registro.
- O campo **origem** distingue `projeto`, `projeto_registrado`, `observada` e `inferida_entre_vizinhas`. Uma geometria inferida descreve a hipótese de continuidade do plantio, não uma observação de cultura onde há solo vazio.

Bases consultadas: [Maldaner et al., 2021 — comparação de sensores para medir falhas](https://www.sciencedirect.com/science/article/abs/pii/S1537511021001409), [Mapping Gaps in Sugarcane by UAV RGB Imagery](https://www.mdpi.com/2073-4395/11/12/2578) e [RGB Composition… Sugarcane Row Gaps](https://www.mdpi.com/2624-7402/7/1/17). A implementação combina amostragem por fileira, continuidade e tratamento de NoData; seus limiares não são uma calibração universal validada por esses artigos.

A análise por objetos e a separação entre identificação da fileira, vegetação e falhas também se apoiam nas abordagens discutidas em [Mapping skips in sugarcane fields using object-based analysis](https://www.sciencedirect.com/science/article/pii/S0168169917312243) e [Mapping Gaps in Sugarcane Fields Using UAV-RTK Platform](https://www.mdpi.com/2077-0472/13/6/1241). O crescimento por histerese e os limites de área/distância são escolhas desta implementação, verificadas por regressões; não representam um classificador treinado nem garantem identificação botânica infalível.

A avaliação de diferentes índices/limiares e a dependência das condições de iluminação e fundo são discutidas em [A New Vegetation Segmentation Approach for Cropped Fields Based on Threshold Detection from Hue Histograms](https://pmc.ncbi.nlm.nih.gov/articles/PMC5948827/). O uso do RGBVI e dos critérios locais acima é uma adaptação deste projeto, não uma reprodução ou validação dos limiares por esse artigo. [Mapping Gaps… Using YOLOv5 and ImageJ](https://www.mdpi.com/2076-3417/14/17/7454) também discute as limitações da identificação de falhas curtas com crescimento do dossel, inclusive em avaliações do Inforow. Quantidade maior de falhas não prova maior acurácia.

### Parâmetros e Atributos Gerados

- **Imagem de referência (raster)** e **Nuvem de pontos classificados como cultura**.
- **Espaçamento esperado entre linhas (m)**: Distância nominal entre fileiras adjacentes (padrão: `1,5 m`).
- **Deslocamento lateral máximo por metro longitudinal (m/m)**: Curvatura/desvio lateral permitido no rastreamento (padrão: `1,0 m/m`).
- **Maior lacuna longitudinal que pode ser interpolada (m)**: Comprimento máximo de falha contínua que o rastreador pode transpor na mesma fileira (padrão: `10,0 m`).
- **Mínimo de pontos na densidade local para reconhecer a fileira**: Sensibilidade mínima de suporte local (padrão: `4`).
- **Saídas Vetoriais**:
  1. **Linhas de plantio restituídas (`OUTPUT`)**: Camada `LineString` com os atributos:
     - `linha_id`: Identificador sequencial da fileira (`1, 2, ...`).
     - `angulo_graus`: Orientação média da fileira em graus (`0°–180°`).
     - `compr_m`: Comprimento total da fileira restituída (m).
     - `falha_m`: Comprimento total das falhas que atingem o mínimo configurado (m).
     - `falha_pct`: Percentual de falha sobre o comprimento com dados (`0–100%`).
     - `num_falhas`: Quantidade de trechos que atingem o mínimo configurado.
     - `sem_dados_m`: Comprimento não avaliado por falta de imagem válida.
     - `incerto_m`: Comprimento com evidência ambígua, excluído da contagem de falhas confirmadas.
     - `amostra_cm`: Passo efetivo de amostragem, em centímetros.
     - `pct_pes`: Percentual do comprimento com apoio aceito para centralização.
     - `pct_proj`: Percentual do comprimento protegido e mantido na referência por falta de apoio confiável.
     - `origem`: Proveniência geométrica da fileira; identifica a inferência entre vizinhas e o registro de projeto.
  2. **Segmentos de falha de plantio (`OUTPUT_GAPS`, opcional)**: camada `LineString` com `falha_id`, `linha_id`, `compr_m` e `categoria`, respeitando o mínimo configurado em centímetros.
  3. **Trechos incertos ou sem dados para revisão (`OUTPUT_REVIEW`, opcional)**: ative esta saída para visualizar onde o algoritmo não conseguiu concluir presença ou ausência. Contém `linha_id`, `compr_m` e `motivo` (`incerto` ou `sem_dados`). Esses trechos não são falhas confirmadas e não são filtrados pelo mínimo de falha. A saída é dispensável no fluxo normal e não altera as linhas.

Em comparações com outras ferramentas, alinhe o mínimo de falha, a área avaliada, o CRS métrico e as linhas de referência. Contagem de segmentos e sobreposição entre programas medem diferenças/concordância, não acurácia de campo. Examine o RGB e os trechos de revisão antes de interpretar uma camada com menos falhas como melhor.

---

## Referências Metodológicas

O estado de aprovação, o escopo e as instruções para reproduzir os testes estão em [VALIDACAO.md](VALIDACAO.md). Após a reestruturação 2.4, os nove cenários da bateria de aceitação passaram pelos critérios originais. Essa aprovação é restrita aos ensaios executados; não é uma estimativa de acurácia agronômica em todos os talhões.

- Rocha et al. (2023) — *Automatic detection and evaluation of sugarcane planting rows from UAV RGB imagery* ([DOI: 10.1016/j.inpa.2022.04.003](https://doi.org/10.1016/j.inpa.2022.04.003))
- Souza et al. (2017) — *Mapping skips in sugarcane fields using object-based image analysis* ([DOI: 10.1016/j.compag.2017.10.006](https://doi.org/10.1016/j.compag.2017.10.006))
- Junqueira et al. (2021) — *Effect of spatial resolution and sugarcane stage on skip detection* ([DOI: 10.3390/agronomy11122578](https://doi.org/10.3390/agronomy11122578))

---

## Instalação e Requisitos

1. Copie esta pasta para o diretório de plugins do QGIS (`%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins`) ou instale via arquivo ZIP em **Plugins → Gerenciar e Instalar Plugins → Instalar a partir de ZIP**.
2. Requer **QGIS 3.22 ou superior** com as bibliotecas padrão distribuídas no ambiente Python do QGIS (`GDAL`, `NumPy` e `SciPy`).

### Bases do refinamento de centros

- Eilers (2003), *A perfect smoother*: ajuste por mínimos quadrados penalizados. [Artigo](https://pubmed.ncbi.nlm.nih.gov/14570219/)
- *Mapping skips in sugarcane fields using object-based analysis of UAV images*: identificação separada das fileiras, vegetação e falhas. [Artigo](https://www.sciencedirect.com/science/article/pii/S0168169917312243)
- *Pixel-wise navigation line extraction of cross-growth-stage seedlings in complex sugarcane fields*: detecção de vegetação e ajuste de linhas de navegação. [Artigo](https://pmc.ncbi.nlm.nih.gov/articles/PMC11823478/)

O uso conjunto de núcleo morfológico, votos de folhas e limites de flexão é uma implementação deste projeto, e ainda precisa ser validado com dados reais.

O uso do contexto espacial e da organização em fileiras como evidência complementar é discutido por [Lottes et al., ICRA 2017](https://www.ipb.uni-bonn.de/wp-content/papercite-data/pdf/lottes17icra.pdf). A dificuldade de distinguir cana e invasoras em condições reais é documentada em [Papa et al., 2026](https://www.nature.com/articles/s44387-026-00096-0). Esses trabalhos motivam a decisão conservadora de preservar a referência na incerteza; não validam os limiares escolhidos aqui.
