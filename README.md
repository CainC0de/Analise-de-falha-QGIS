# Falha de Plantio — Plugin QGIS (v2.3)

Plugin para o QGIS voltado à **análise automatizada de falhas de plantio na cultura de cana-de-açúcar** a partir de ortomosaicos RGB de drones/VANTs.

O fluxo do plugin é composto por duas ferramentas principais na Caixa de Ferramentas de Processamento (**Falha de Plantio (Cana-de-açúcar) → Análise de falhas**):

1. **Classificar vegetação verde (RGB)** (`falhadeplantio:classificar_vegetacao_rgb`)
2. **Restituir linhas de plantio a partir dos pontos** (`falhadeplantio:restituir_linhas_plantio`)

---

## 1. Classificar vegetação verde (RGB)

Classifica a cobertura vegetal da cana-de-açúcar em imagens RGB e gera simultaneamente um raster temático (GeoTIFF) e uma nuvem de pontos representativa das touceiras/fileiras da cultura (GeoPackage).

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
4. **Processamento em Blocos via VRT Dinâmico**:
   - A leitura e eventual reprojeção para UTM ocorrem sob demanda em memória via `GDAL VRT`, sem gravar arquivos temporários gigantescos em disco e mantendo a resolução espacial efetiva da imagem.

### Parâmetros de Entrada e Saída

- **Raster de entrada (imagem RGB)**: Ortomosaico RGB (com ou sem banda Alpha). Se estiver em coordenadas geográficas (graus), é reprojetado automaticamente para a zona UTM métrica local.
- **Bandas R, G e B**: Índices das bandas vermelha, verde e azul (padrão: `1`, `2`, `3`).
- **Tamanho do pixel de saída (cm)**: Resolução desejada para o GeoTIFF classificado (padrão: `5,0 cm`; preserva a resolução nativa caso o raster original seja mais grosseiro, evitando superamostragem artificial).
- **Espaçamento aproximado entre pontos da nuvem (cm)**: Tamanho da célula espacial usada para agregar pixels de cultura em um ponto centroide representativo (padrão: `20,0 cm`).
- **Ajuste fino de sensibilidade GLI**: Valor de calibração fina sobre o limiar adaptativo automático (padrão: `0,0`; valores positivos tornam a detecção mais restritiva e valores negativos mais permissiva).
- **Saídas**:
  - **Classificação de vegetação (GeoTIFF)**: `1` = vegetação verde (verde), `0` = palhada/solo sem vegetação (vermelho), `255` = NoData (transparente).
  - **Nuvem de pontos da cultura (GeoPackage)**: Camada vetorial `Point` contendo os atributos `gli` (GLI médio na célula), `classe` (`1`) e `pixel_count` (quantidade de pixels verdes agregados).

---

## 2. Restituir linhas de plantio a partir dos pontos

Reconstrói o traçado vetorial contínuo de cada linha de plantio — acompanhando **linhas retas, curvas de nível, terraços embutidos e múltiplos talhões com orientações distintas** — e quantifica as **falhas de plantio** ao longo de cada fileira.

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
   - Ao longo de cada linha restituída, verifica a presença efetiva de cultura e identifica todos os trechos internos sem cobertura vegetal com extensão $\ge 0,50\text{ m}$ como **falhas de plantio**.

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
     - `falha_m`: Comprimento total somado das falhas de plantio ($\ge 0,5\text{ m}$) na fileira (m).
     - `falha_pct`: Percentual de falha da fileira (`0–100%`).
     - `num_falhas`: Quantidade de trechos de falha ($\ge 0,5\text{ m}$) contabilizados na fileira.
  2. **Segmentos de falha de plantio (> 0,5 m) (`OUTPUT_GAPS`, opcional)**: Camada `LineString` demarcando exatamente a geometria de cada trecho de falha detectado ao longo das fileiras, com os atributos `falha_id`, `linha_id` e `compr_m`.

---

## Referências Metodológicas

- Rocha et al. (2023) — *Automatic detection and evaluation of sugarcane planting rows from UAV RGB imagery* ([DOI: 10.1016/j.inpa.2022.04.003](https://doi.org/10.1016/j.inpa.2022.04.003))
- Souza et al. (2017) — *Mapping skips in sugarcane fields using object-based image analysis* ([DOI: 10.1016/j.compag.2017.10.006](https://doi.org/10.1016/j.compag.2017.10.006))
- Junqueira et al. (2021) — *Effect of spatial resolution and sugarcane stage on skip detection* ([DOI: 10.3390/agronomy11122578](https://doi.org/10.3390/agronomy11122578))

---

## Instalação e Requisitos

1. Copie esta pasta para o diretório de plugins do QGIS (`%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins`) ou instale via arquivo ZIP em **Plugins → Gerenciar e Instalar Plugins → Instalar a partir de ZIP**.
2. Requer **QGIS 3.22 ou superior** com as bibliotecas padrão distribuídas no ambiente Python do QGIS (`GDAL`, `NumPy` e `SciPy`).
