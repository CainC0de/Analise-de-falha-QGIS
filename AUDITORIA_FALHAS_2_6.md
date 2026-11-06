# Auditoria de falhas e continuidade automática — 2.6

Data: 6 de novembro de 2026. Base: `f663f04aead61820bab3f0cb23c03c7a32ea4423`, com alterações locais identificadas pelos manifestos SHA-256.

## Escopo e dados

O usuário confirmou mínimo de **50 cm** e uso do **RGB original** no outro computador. As três capturas indicadas em `Z:/BACKUP 2` não foram encontradas, nem pela sessão do QGIS. Portanto, esta auditoria não afirma ter inspecionado os locais exatos dessas capturas.

Foi usado o talhão RGB, com nuvem de pontos, disponível no QGIS conectado. A comparação principal executa o fluxo completo **sem linhas projetadas**, antes e depois das correções. A camada Inforow serve para localizar divergências; não é verdade de campo. Os dados, coordenadas e capturas do talhão ficam fora do repositório.

## Erros reproduzidos e correções

1. **Ausência longa escondida por folha lateral.** O refinamento tinha teto de 3 m e dependia das duas pontas dentro de um bloco. Um perfil com 5 m de solo no eixo, atravessado por folhagem fina lateral, era classificado integralmente como cultura. A análise agora conserva a evidência por estação e reavalia os intervalos na fileira inteira. O mínimo não foi reduzido. Um ensaio de 35 m atravessa blocos e é testado nos dois sentidos de leitura.
2. **Cultura deslocada fora dos antigos ±35 cm.** Uma faixa de cana verde ou oliva a 42 cm do eixo podia produzir falha total. Núcleos compactos agora também são procurados até ±50 cm, limitados a 35% da entrelinha. A ampliação protege corpos vegetais; uma folha fina isolada não basta. Núcleos externos à faixa são removidos antes da dilatação, evitando empréstimo de uma copa vizinha.
3. **Folhagem clara tratada como solo.** Evidência fraca exigia escurecimento em relação à entrelinha para gerar ambiguidade. Folhagem clara com contraste coerente em RGBVI, azul e excesso de verde agora permanece para revisão mesmo quando essa condição de brilho falha. Isso não a certifica botanicamente como cana.
4. **Fileira quebrada em ausência longa, sem projeto.** Dois fragmentos só são ligados quando duas fileiras observadas os delimitam e cobrem o intervalo. Direção, posição de faixa, espaçamento e apoio observado precisam concordar nas duas pontas. O trecho conectado recebe peso zero de planta e origem `observada_conectada`. Ausência de guia dos dois lados, apoio insuficiente ou outra faixa de plantio impede a conexão.
5. **Outro talhão desativava a conclusão geométrica.** O teste global de paralelismo retornava sem completar a rede quando uma direção incompatível estava presente. A conclusão passou a trabalhar em famílias compatíveis, mantendo a ordem das observações para os atributos.
6. **Pontas ruidosas e inferência sobre fragmentos existentes.** A extrapolação quadrática de cada ponta foi substituída por tendência linear observada em 4 m. A verificação de novas fileiras usa distâncias ao longo do caminho inteiro; uma mediana não pode ocultar um fragmento curto sobre o mesmo traçado.
7. **Borda oblíqua válida perdida.** Parte da faixa transversal pode ficar fora do raster enquanto o eixo continua observado. Esse comprimento só é recuperado com eixo válido, solo central suficiente, fundo comparável e ausência de planta observada. Um buraco de NoData no próprio eixo continua não avaliado.

## Testes

**93 regressões aprovadas**, sem falhas, erros ou testes ignorados, no QGIS 3.44.11, Python 3.12.13 e GDAL 3.13.0. O manifesto identifica os cinco módulos de produção. A matriz completa conserva os dez cenários anteriores e acrescenta ausência de 16 m em tiro reto e curva, ambos sem projeto. **Os 12 cenários passaram**; o maior erro de comprimento foi aproximadamente 5 cm, dentro do limite original de 10 cm.

Os critérios originais continuam: geometria válida, ausência de cruzamentos nos cenários, uma parte por fileira, pelo menos 95% da referência a até 10 cm, correspondência das falhas, nenhuma previsão sem correspondência, erro de comprimento até 10 cm e mínimo de 50 cm. Os cenários ampliados têm seis falhas esperadas; os outros cenários com falhas têm oito. O controle saudável continua sem falhas previstas.

Os controles negativos exigem recusa de ligação sem vizinhas dos dois lados, com orientação/faixa incompatível ou guias sem apoio. Outros controles preservam a planta curta no centro, a touceira deslocada, NoData, sombra, cana amarelada e os limites de leitura. A fixture de copa externa foi deslocada para fora dos novos ±50 cm, conservando a exigência de que vegetação externa não confirme cultura no corredor.

A conferência de novas inferências inclui observações de todas as famílias de orientação. Linhas com poucos vértices são densificadas em distância física antes dessa verificação; seus segmentos não podem ser ignorados porque só uma extremidade foi amostrada. Fragmentos não ligados por duas guias também não podem extrapolar longitudinalmente um através do outro.

Em 20 linhas reais sorteadas (semente 20261106), as mesmas coordenadas foram medidas nos dois sentidos: **zero estações com classe diferente**. O controle registra os hashes do classificador e não inverte a fase da amostragem.

Uma ausência de 35 m com 1 m de NoData interno permanece em **duas partes observadas**, sem unir através da região desconhecida. Os testes não eliminam amostras de cultura para alcançar o mínimo. A mesma fase e as mesmas coordenadas são comparadas na reversão do perfil.

Reprodução: use `scripts/validate_acceptance_qgis.py` dentro de um QGIS inicializado. Execute `run_regressions(output)` e cada cenário de `CASES`, um por chamada. Não abra uma segunda QApplication para esses testes.

## Execução no talhão disponível

As duas execuções abaixo usaram o mesmo RGB, a mesma nuvem, entrelinha de 1,5 m e mínimo de 50 cm, **sem linhas projetadas**. Os resultados 2.4/2.4.1 com projeto registrados anteriormente não constituem a referência desta comparação.

| Auditoria | Referência 2.5 | Revisão 2.6 |
| --- | ---: | ---: |
| Linhas | 241 | 241 |
| Comprimento de linhas | 52.131,45 m | 52.113,96 m |
| Pares de linhas cruzadas | 11 | **0** |
| Geometrias inválidas, linhas ou falhas | 0 | 0 |
| Falhas fora da linha associada, tolerância 1 mm | 0 | 0 |
| Segmentos de falha | 5.239 | 4.437 |
| Comprimento de falhas | 4.757,75 m | 4.163,59 m |
| Segmentos de pelo menos 3 m | 145 | 150 |
| Comprimento incerto | 385,57 m | 334,25 m |

A execução final levou 210,7 s, incluindo reconstrução, medição e gravação. A referência levou 168,0 s. Foram executados outros controles durante essas rodadas; esses tempos não são um benchmark isolado. A revisão acrescenta verificações e não demonstrou uma redução do tempo total. O cache nativo continua limitado a 32 MiB, além das demais estruturas do processamento.

Na área comum com o Inforow — polígono do talhão intersectado com a cobertura nativa do RGB — a revisão teve 4.432 segmentos elegíveis, somando 4.160,11 m. O Inforow teve 5.015, somando 4.904,04 m. Com tolerância lateral de 30 cm, 75,45% do comprimento da revisão coincidiu com o Inforow; no sentido inverso, 65,95%. Na referência 2.5, os valores eram 70,08% e 68,40%.

Portanto, a concordância aumentou em um sentido e diminuiu no outro. A redução de segmentos não prova que todos os removidos eram falsos positivos, nem que todas as marcações adicionais do Inforow sejam falhas verdadeiras. A inspeção exploratória conserva 24 geometrias de divergência e seus RGB, além da comparação das mesmas amostras após a mudança. A geometria de uma amostra distante da fileira correspondente não deve ser usada para avaliar a classificação ao longo dela.

Nenhuma conexão por duas guias e nenhuma nova fileira inferida foi aceita na execução final deste talhão. Essas possibilidades passaram nos ensaios controlados; três inferências conflitantes de uma rodada intermediária foram recusadas pelo controle global. Os resultados intermediários não são a versão de entrega. O grupo de comparação 2.6 no QGIS aponta para os arquivos finais, sem substituir as camadas anteriores.

## Interpretação

O objetivo é reduzir erros reproduzíveis com controles explícitos, não igualar a contagem de outra ferramenta. A largura ampliada pode proteger vegetação que se projeta sobre o corredor; a distinção entre folhas, colmos, invasoras e palhada ainda depende da imagem e de verificação. Cana sob dossel fechado ou uma área totalmente vazia sem referências geométricas suficientes não se torna identificável apenas por aumentar a sensibilidade.

Os testes sintéticos são funcionais, não uma estimativa de precisão/recall agronômico. A inspeção de divergências no mesmo talhão durante desenvolvimento também não é validação independente. Não foi treinada uma rede neural ou um classificador botânico com rótulos de campo neste trabalho.

## Referências consultadas

- [Rocha et al., detecção e avaliação de fileiras em imagens aéreas](https://doi.org/10.1016/j.inpa.2022.04.003): segmentação espectral, morfologia e geometria para identificar fileiras e medir intervalos.
- [Junqueira et al., influência da resolução e do estágio da cana](https://www.mdpi.com/2073-4395/11/12/2578): resolução e sobreposição do dossel condicionam o que o RGB consegue observar.
- [Classificação com invasoras e sensores multiespectrais](https://doi.org/10.1016/j.atech.2025.100780): a distinção entre cana e não cana exige evidência; as bandas e métricas desse trabalho não foram transferidas a um plugin apenas RGB.
- [Maldaner et al., comparação de sensores para falhas](https://doi.org/10.1016/j.biosystemseng.2021.06.016): a cobertura vista do alto difere da observação de colmos sob o dossel.

As regras e os limiares desta revisão são próprios do projeto. Esses artigos motivam a separação entre observação, geometria e incerteza; não validam automaticamente a implementação.
