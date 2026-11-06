# 12 — Testes, métricas e reprodução

[Índice](README.md) · Fonte: [validate_acceptance_qgis.py](../scripts/validate_acceptance_qgis.py) e [testes](../test).

## Camadas de verificação

| Grupo | O que verifica |
| --- | --- |
| `test_planting_gaps.py` | Estados, cor, plantas pequenas/deslocadas, NoData, mínimo, fronteiras de leitura e núcleos |
| `test_cane_centers.py` | Núcleos, subpixel, contexto, outliers e limites do ajuste |
| `test_rgb_preparation.py` | Recorte, CRS, alpha, buracos, saídas e validações |
| `test_row_network.py` | Conexão apoiada, recusas, famílias, inferência e extensão das pontas |
| `test_acceptance_pipeline.py` | Fluxo completo com verdade geométrica definida antes da execução |

`run_regressions()` carrega explicitamente esses cinco módulos. Os testes legados de interface/tradução e o alvo antigo `make test` não equivalem automaticamente à bateria dessa função.

## Matriz completa da revisão 2.6

| Cenário em `CASES` | Característica |
| --- | --- |
| `straight` | Tiro reto com projeto |
| `straight_shifted` | Projeto deslocado em 15 cm |
| `contour` | Curva de nível com projeto |
| `oblique` | Direção de 33° com projeto |
| `yellow` | Cana amarelada controlada |
| `automatic` | Tiro reto sem projeto |
| `automatic_healthy` | Cinco fileiras saudáveis, sem falhas |
| `automatic_oblique` | Direção oblíqua sem projeto |
| `automatic_contour` | Curva sem projeto |
| `short_gap_leaf_overlap` | Folha lateral atravessando falha de 50 cm |
| `automatic_large_gap` | Falha de 16 m sem projeto |
| `automatic_large_contour_gap` | Falha de 16 m em curva, sem projeto |

`make_fixture()` cria o RGB, alpha, linhas verdadeiras e intervalos esperados. `run_case()` executa o classificador e usa sua nuvem na restituição real. Não substitui a restituição por uma geometria pronta para avaliar apenas a medição.

## Critérios do auditor sintético

`audit()` verifica geometria válida, cruzamentos, uma parte por fileira, cobertura de pelo menos 95% a até 10 cm da referência, correspondência individual das falhas, ausência de previsões sem correspondência, erro de comprimento até 10 cm e mínimo de 50 cm.

O pareamento de falhas usa corredor de 10 cm e sobreposição mínima de 70% nos dois comprimentos, com atribuição um a um. Há contagens separadas para falhas próximas do limite e acima de 60 cm. Essas tolerâncias são critérios de engenharia da bateria, não uma norma de certificação agronômica.

Na execução documentada da 2.6: **93 regressões aprovadas, 12 cenários aprovados**, maior erro de comprimento aproximadamente 5 cm. Não se deve transportar esses números para uma revisão com código diferente sem nova execução.

## Executar dentro do QGIS

Use uma sessão QGIS já inicializada. Não crie outra `QApplication` nem execute um Python QGIS avulso para esses ensaios.

```python
import importlib.util
from pathlib import Path

repo = Path(r"CAMINHO_DO_REPOSITORIO")
output = Path(r"PASTA_NOVA_PARA_RESULTADOS")
spec = importlib.util.spec_from_file_location(
    "acceptance", repo / "scripts/validate_acceptance_qgis.py"
)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)

print(acceptance.run_regressions(output))
print(acceptance.run_case("automatic_large_contour_gap", output))
# Execute os outros nomes de acceptance.CASES, um por chamada.
```

Os destinos devem ser novos para não misturar resultados. Cada cenário grava RGB, verdade geométrica, GeoPackages e JSON de métricas. A regressão grava relatório textual, tempos, ambiente e hashes dos cinco módulos de produção. `load_algorithms()` usa uma assinatura desses módulos na importação para evitar cache de código antigo.

## Talhão real e Inforow

A [auditoria 2.6](../AUDITORIA_FALHAS_2_6.md) registra uma execução completa sem projeto no RGB disponível: 241 linhas, zero geometrias inválidas, zero cruzamentos e zero falhas fora da linha associada na tolerância de 1 mm. Em 20 fileiras, a mesma amostragem invertida teve zero classes diferentes.

Comparar duas ferramentas exige o mesmo mínimo, CRS métrico, cobertura útil e polígono. O recorte pode criar partes menores que o mínimo: cada parte precisa ser reavaliada, não apenas a feição original. Tolerância lateral e comprimento de sobreposição devem ser declarados.

Concordância com Inforow não é precisão/recall de campo. Mais segmentos podem representar ausências reais adicionais ou falsos positivos; menos segmentos podem representar proteção de plantas ou omissões. A inspeção de divergências durante desenvolvimento não constitui uma amostra independente de certificação.

Para validar agronomicamente outro conjunto, são necessários rótulos independentes, regiões/estágios representativos, limites de falha conferidos e critérios de pareamento fixados antes de ajustar o código. RGB de dossel fechado não fornece observação direta de todo colmo.
