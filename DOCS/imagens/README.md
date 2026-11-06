# Figuras de referência e sua origem

[Documentação](../README.md) · [README principal](../../README.md).

## Fotografias e mapas

| Arquivo | Origem e interpretação |
| --- | --- |
| `ortomosaico_rgb.jpg` | Recorte renderizado no QGIS a partir do RGB disponível na sessão da auditoria 2.6 |
| `linhas_e_falhas.jpg` | Mesmo recorte e enquadramento, com linhas automáticas verdes e falhas laranja da execução final, mínimo de 50 cm |
| `antes_depois_pontas.png` | Mesmo local real em duas renderizações: geometrias de referência 2.5 e revisão 2.6 |

As imagens são representações dos dados e resultados analisados. Não foram sintetizadas por IA. As sobreposições mostram a saída do algoritmo, não anotações independentes da posição de cada colmo. As figuras não contêm grade de coordenadas nem arquivos de georreferenciamento associados.

## Gráficos

| Arquivo | Dados utilizados |
| --- | --- |
| `validacao_sintetica.svg` | Erro máximo de comprimento de cada um dos 12 cenários completos |
| `integridade_geometrica.svg` | Auditoria de cruzamentos, validade e associação de segmentos às linhas |
| `comparacao_inforow.svg` | Concordância de comprimento, nos dois sentidos, em área comum e corredor de 30 cm |

Os gráficos são gerados com Matplotlib, sem alterar ou interpolar os valores dos relatórios. Os dados agregados utilizados estão em [validacao_2_6.json](../dados/validacao_2_6.json). O conjunto não publica os rasters completos, os GeoPackages ou os caminhos locais das entradas.

## Reproduzir as figuras

[build_documentation_assets.py](../../scripts/build_documentation_assets.py) utiliza o diretório local de auditoria, os relatórios de testes e o RGB já aberto no QGIS. Também confere os hashes dos cinco módulos de produção antes de gerar gráficos, para evitar atribuir resultados de outra implementação à versão atual.

Execute no console Python de um QGIS inicializado, com Matplotlib disponível:

```python
import importlib.util
from pathlib import Path

repo = Path(r"CAMINHO_DO_REPOSITORIO")
spec = importlib.util.spec_from_file_location(
    "documentation_assets", repo / "scripts/build_documentation_assets.py"
)
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)
assets.build()
```

O script pressupõe a estrutura local de resultados `validacao_centros/revisao_2_6` ao lado do repositório e a camada RGB `Recortado (mascara)` na sessão. Esses dados de auditoria não acompanham o código-fonte; sem eles, a reprodução requer preparar resultados equivalentes e adaptar a origem de dados. O script não executa novamente a análise agrícola e não modifica as camadas do projeto aberto.

O inventário de funções em `DOCS/13_MAPA_DO_CODIGO.md` é extraído por AST do código local. Gráficos e inventário precisam ser regenerados ou revisados quando o código e os resultados mudarem.
