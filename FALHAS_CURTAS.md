# Falhas curtas visíveis — revisão 2.5

Data: 5 de novembro de 2026. Base: código local sobre `b7b3b3452bc7ac863d6bdd018bdbe47150280b29`.

## Problema e método

Uma folha lateral dentro da faixa de avaliação podia confirmar cultura durante parte de um intervalo com solo visível no eixo. Isso encurtava ou fragmentava uma falha real próxima do mínimo de 50 cm. A simples redução da largura da faixa perderia touceiras deslocadas; eliminar toda vegetação curta apagaria plantas verdadeiras.

A revisão mantém o perfil espectral anterior e acrescenta uma decisão espacial opcional. A transformada de distância procura regiões espessas do objeto vegetal; máximos locais, dilatação métrica limitada e uma proteção complementar para objetos pequenos compactos representam evidência de touceira. Esses núcleos vetam a recuperação de ausência, inclusive fora do eixo. Solo visível predominante no centro pode então superar uma resposta periférica fina, desde que haja núcleos próximos nas duas extremidades. A linha restituída permanece independente dessa decisão.

Restrições explícitas:

- passo longitudinal e transversal de até 6 cm, sem criar detalhe artificial;
- pelo menos 90% de validade e 80% de solo reconhecido na faixa central de até ±10 cm;
- veto por ocupação vegetal central ou núcleo compacto no corredor da própria fileira;
- intervalo visível de até `min(3 m, 2 × espaçamento)`, apoiado por núcleos a até 30 cm nas duas extremidades;
- NoData nunca se transforma em ausência; sombra sem evidência de solo permanece incerta;
- o mínimo configurado continua inclusivo e é aplicado ao comprimento medido ao longo da linha;
- máscara binária e resolução insuficiente conservam o comportamento anterior.

O parâmetro **Melhorar detecção de falhas curtas com solo visível (RGB)** vem ativado e permite uma comparação controlada com a medição anterior. O novo campo `evidencia` informa `solo_e_nucleo` quando esse refinamento contribuiu para alguma parte do segmento. Não significa que todo o segmento tenha sido inferido por esse método, nem fornece confiança estatística.

## Eficiência

A amostragem lê somente blocos nativos de 256 × 256 pixels tocados pela faixa e conserva um cache limitado a 32 MiB. Isso reduz leituras desnecessárias nos grandes retângulos que envolvem fileiras diagonais. O cache conserva dados brutos; somente as amostras consultadas são convertidas. O limite não inclui as demais estruturas da restituição ou o cache interno do GDAL.

## Verificação reproduzível

**75 testes de regressão aprovados**, sem falhas, erros ou testes ignorados, no QGIS 3.44.11 / Python 3.12.13 / GDAL 3.13.0. O manifesto da execução conserva SHA-256 dos cinco módulos de produção.

Controles novos:

- falha visível de exatamente 50 cm atravessada por folha lateral: recuperada pelo refinamento, omitida com a opção desativada;
- touceira compacta deslocada: continua interrompendo a ausência;
- planta curta no centro: continua interrompendo a ausência;
- faixa fina sem núcleos nas duas pontas: não é convertida em falha total;
- leitura de cores diferentes em ambos os lados de fronteiras entre blocos: corresponde aos pixels solicitados;
- fluxo completo RGB → nuvem → linhas → falhas: a recuperação de 50 cm mantém exatamente o mesmo hash geométrico das linhas e grava a evidência no GeoPackage.

Também permanecem aprovados os controles anteriores de cana oliva/amarelada, sombra, palhada, NoData, curvas, mínimo inclusivo e invariância de leitura do caso sintético com larguras variáveis. O cenário adicional `short_gap_leaf_overlap` tem verdade geométrica definida antes da execução; não altera o mínimo ou as tolerâncias da bateria original.

Os dez cenários completos desta revisão passaram: tiro reto, projeto deslocado, curva de nível, direção oblíqua, cana amarelada, os quatro cenários automáticos anteriores e o novo cenário com folha lateral. Nos nove cenários com falhas, foram correspondidas as oito falhas esperadas; no controle saudável não houve falhas previstas. Permaneceram os limites originais de geometria, cobertura, comprimento e mínimo. Essa rodada antecedeu apenas a edição da ajuda do algoritmo; a regressão final registra os hashes posteriores e inclui novamente o fluxo de recuperação de 50 cm.

A nova execução integral no talhão, o cronômetro de desempenho e a conferência adicional de novas marcações **ainda estão pendentes**. A conexão MCP ficou bloqueada por uma janela de erro Python durante o registro do provedor de auditoria, e a área de trabalho estava bloqueada. O registro de auditoria foi corrigido, mas não foi retomado sem o fechamento da janela. Não há resultados novos de campo ou redução de tempo medidos que possam ser atribuídos à revisão 2.5.

Reprodução no console de um QGIS inicializado:

```python
import importlib.util
from pathlib import Path
repo = Path(r"CAMINHO_DO_REPOSITORIO")
output = Path(r"PASTA_NOVA_DE_RESULTADOS")
spec = importlib.util.spec_from_file_location("acceptance", repo / "scripts/validate_acceptance_qgis.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
print(acceptance.run_regressions(output))
print(acceptance.run_case("short_gap_leaf_overlap", output))
# Execute os outros nomes de acceptance.CASES, um por chamada.
```

Os dados e imagens do talhão real ficam fora do repositório. Inspeções de divergências com outra ferramenta são exploratórias e não substituem medições de campo. Uma amostra usada durante desenvolvimento não deve ser apresentada como validação independente.

## Base metodológica e alcance

[Souza et al. (2017), Mapping skips in sugarcane fields using object-based image analysis](https://doi.org/10.1016/j.compag.2017.10.006) motiva separar fileiras, objetos vegetais e ausências. [Rocha et al. (2023), Automatic detection and evaluation of sugarcane planting rows from UAV RGB imagery](https://doi.org/10.1016/j.inpa.2022.04.003) combina informação espectral e operações morfológicas. A adaptação implementada aqui usa esses princípios, com regras próprias para distinguir folha lateral e núcleo compacto; não reproduz os classificadores ou transfere as métricas de acurácia desses artigos.

[Mapping Gaps in Sugarcane Fields Using UAV-RTK Platform](https://www.mdpi.com/2077-0472/13/6/1241) e [Mapping Gaps… Using YOLOv5 and ImageJ](https://www.mdpi.com/2076-3417/14/17/7454) documentam a influência do desenvolvimento e fechamento do dossel. Este plugin não recebeu um modelo YOLO treinado. O RGB não comprova ausência de colmos sob folhas sobrepostas; plantas pequenas, invasoras, iluminação e resolução podem continuar exigindo revisão. Aprovação dos controles descritos não é garantia de identificação perfeita em qualquer talhão.
