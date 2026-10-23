# Falha de Plantio — Plugin QGIS

Plugin QGIS para análise de falhas em canaviais. Classifica cobertura verde em
uma imagem RGB, gera uma nuvem de pontos da cultura e restitui linhas de plantio.

## Classificação RGB

O algoritmo **Classificar vegetação verde (RGB)** aparece na Caixa de
Ferramentas de Processamento em **Falha de Plantio → Análise de falhas**.

1. Selecione o raster RGB de entrada.
2. Confira/ajuste os números das bandas vermelha, verde e azul (padrão: 1, 2 e 3).
3. Informe o tamanho do pixel de saída em centímetros (padrão: 3 cm).
4. Ajuste o limiar GLI, se necessário (padrão: 0).
5. Escolha o GeoTIFF classificado e o GeoPackage da nuvem de pontos e execute.

O algoritmo calcula pixel a pixel o índice **GLI**:

```text
GLI = (2 × G − R − B) / (2 × G + R + B)
```

Valores acima do limiar recebem classe `1` (verde); os demais recebem `0` (sem
vegetação verde); pixels NoData recebem `255`. A tabela de cores mostra a classe
1 em verde e a classe 0 em vermelho. O cálculo é feito em blocos para limitar o
uso de memória e a imagem RGB é reamostrada para o tamanho solicitado antes da
classificação. O algoritmo também gera uma camada de pontos em GeoPackage com
um ponto no centro de cada pixel classificado como vegetação; o campo `gli`
guarda o índice calculado e `classe` vale `1`.

O tamanho do pixel define a resolução espacial de saída. Ele não cria detalhe
que não exista na imagem original. Se o raster estiver em graus ou em unidades
não métricas, o plugin o reprojeta automaticamente para a zona UTM local para
aplicar a resolução em centímetros. Para imagens RGB, o GLI
detecta cobertura verde, mas não distingue cana-de-açúcar de ervas daninhas;
essa distinção requer contexto adicional, como linhas de plantio, outras bandas
espectrais ou uma etapa de classificação treinada.

A nuvem gerada a partir de uma imagem RGB é 2D. Para criar pontos 3D em LAS/LAZ,
é necessário fornecer também um raster de elevação ou outro dado de altitude.

## Restituição das linhas

O algoritmo **Restituir linhas de plantio a partir dos pontos** recebe a imagem
raster e a nuvem de pontos gerada na etapa anterior. Ele estima a orientação e
o espaçamento das fileiras, agrupa os pontos por linha e cria uma camada
vetorial com traçados ajustados localmente aos pontos. Cada linha é ajustada de
forma independente para preservar pequenas curvas e variações observadas no
campo. O espaçamento esperado (padrão: 1,5 m), a largura de associação dos
pontos, a densidade mínima por trecho e o maior intervalo a interpolar podem ser
ajustados. Picos compatíveis com a grade do plantio são priorizados para reduzir
linhas duplicadas; cada trecho usa a mediana transversal dos pontos para diminuir
o deslocamento causado por pontos isolados. A imagem original pode estar em outro
CRS; o algoritmo confere a sobreposição e grava as linhas no CRS métrico da nuvem
de pontos.

## Instalação

Use **Plugins → Gerenciar e Instalar Plugins → Instalar a partir de ZIP** no
QGIS, ou copie esta pasta para o diretório de plugins do perfil QGIS.

Requer QGIS 3.22 ou superior e as bibliotecas GDAL e NumPy distribuídas com o
QGIS.
