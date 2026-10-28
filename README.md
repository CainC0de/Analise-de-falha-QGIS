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
classificação. O GeoTIFF guarda a classificação em todos os pixels. Para evitar
criar milhões de feições redundantes, a nuvem vetorial agrega pixels verdes em
células espaciais: por padrão, cada ponto resume uma célula de aproximadamente
10 cm. O espaçamento pode ser ajustado na entrada **Espaçamento aproximado entre
pontos da nuvem**. A geometria fica no centroide dos pixels verdes da célula;
`gli` guarda o GLI médio, `classe` vale `1` e `pixel_count` informa quantos pixels
verdes foram agregados. Em áreas muito grandes, o espaçamento pode aumentar
automaticamente para limitar a memória usada pela grade de agregação. A saída
raster continua mantendo a resolução completa solicitada.

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
raster e a nuvem de pontos gerada na etapa anterior. Ele estima a orientação
predominante e constrói perfis locais de densidade em estações sucessivas ao
longo do talhão. Os centros das fileiras são associados de uma estação à próxima,
permitindo que cada traçado acompanhe curvas de nível e mudanças locais de
direção. A orientação também considera a repetição no espaçamento entre fileiras
e reduz confusões com a repetição das plantas ao longo de uma fileira.

O espaçamento esperado (padrão: 1,5 m), o deslocamento lateral máximo por metro
longitudinal, a densidade mínima para reconhecer um centro e a lacuna máxima a
interpolar (padrão: 10 m) podem ser ajustados. Picos locais com suporte suficiente
são rastreados de uma estação à próxima; picos muito próximos são suprimidos para
reduzir duplicações dentro da mesma fileira. A acumulação esparsa preserva o
passo de análise sem alocar uma grade densa para toda a área. O algoritmo também
lê apenas os pontos dentro da extensão do raster e grava a saída no CRS métrico
da nuvem.

## Base metodológica e limites

Estudos brasileiros de restituição de fileiras de cana usam segmentação da
vegetação, estimativa de orientação por gradiente RGB, ajuste curvo das fileiras
e comparação com traçados ou medições manuais. Um método publicado reportou erro
inferior a 2% para comprimento de falhas em sua área e condições avaliadas; esse
resultado não se transfere automaticamente para outras imagens ou fases da
cultura. Outros trabalhos organizam a tarefa em detectar as fileiras, mapear a
cana dentro de cada fileira e, então, medir os trechos vazios.

O limiar GLI identifica cobertura verde, não identifica a espécie. Ervas daninhas,
sombras, solo exposto, resolução espacial, altura e estágio da cana alteram o
resultado. Por isso, as linhas e a nuvem são produtos de análise e precisam ser
validados em cada tipo de imagem antes de orientar decisões de replantio. Para
medições de falhas mais confiáveis, a máscara classificada deve ser analisada ao
longo das linhas e comparada com referências de campo.

Referências metodológicas: [Rocha et al. (2023), detecção automática e avaliação
de linhas de plantio](https://doi.org/10.1016/j.inpa.2022.04.003);
[Souza et al. (2017), mapeamento de falhas com análise orientada a objetos](https://doi.org/10.1016/j.compag.2017.10.006);
[Junqueira et al. (2021), efeito da resolução e estágio da cana na detecção de
falhas](https://doi.org/10.3390/agronomy11122578).

## Instalação

Use **Plugins → Gerenciar e Instalar Plugins → Instalar a partir de ZIP** no
QGIS, ou copie esta pasta para o diretório de plugins do perfil QGIS.

Requer QGIS 3.22 ou superior e as bibliotecas GDAL e NumPy distribuídas com o
QGIS.
