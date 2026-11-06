# 13 — Mapa do código e manutenção da documentação

[Índice](README.md).

## Pontos de entrada

| Operação | Caminho de leitura |
| --- | --- |
| Carregar/descarregar plugin | `classFactory` → `FalhaDePlantioPlugin` → provedor Processing |
| Preparar/classificar/gerar nuvem | `FalhaDePlantioAlgorithm.initAlgorithm` → `processAlgorithm` |
| Restituir/medir | `RestituirLinhasAlgorithm.initAlgorithm` → `processAlgorithm` |
| Alterar definição de presença/ausência final | `GapRasterSampler.states` → `classify_cross_sections` → intervalos |
| Alterar somente a geometria | Rastreamento, ajuste de centros e rede; conferir medição posterior |

## Como manter este catálogo

1. Atualizar o capítulo correspondente ao alterar uma fórmula, limiar, faixa, unidade ou parâmetro.
2. Preservar a distinção entre máscaras, geometria e medição final.
3. Ao mudar saídas, atualizar os contratos e campos do guia 10.
4. Acrescentar controles positivos e de recusa quando houver mudança comportamental.
5. Identificar os módulos testados por hash; não atribuir automaticamente um laudo antigo a uma nova implementação.
6. Verificar os links relativos e diagramas do README e da pasta `DOCS`.

## Arquivos de apoio fora dos algoritmos

- `metadata.txt`: metadados de instalação, versão declarada, dependências mínimas e histórico.
- `pb_tool.cfg`: lista os oito módulos Python e os extras do pacote; a configuração atual não inclui automaticamente toda a pasta `DOCS`.
- `Makefile`: comandos legados de compilação, implantação, documentação e upload. O alvo de testes legado tolera falhas e não substitui o relatório JSON da bateria atual.
- `plugin_upload.py`: utilitário separado para envio de um ZIP ao repositório oficial de plugins por XML-RPC. `main()` faz o envio; `hide_password()` mascara a senha no endereço apresentado. Não é chamado pelos algoritmos de análise nem executado para produzir estes documentos.
- `scripts/build_documentation_assets.py`: gera imagens, gráficos, métricas agregadas e o inventário AST desta documentação, a partir da auditoria local; instruções em [Figuras de referência](imagens/README.md). É uma ferramenta de documentação, sem participação na identificação de cultura.
- `help/source/conf.py` e `i18n`: infraestrutura de ajuda/tradução, sem participação na identificação de cultura.
- `test/utilities.py`, `test/qgis_interface.py` e testes legados: apoio ao ambiente de desenvolvimento.

O inventário a seguir identifica as funções de nível de módulo e métodos declarados nos arquivos de produção. Funções internas, como o cálculo do fundo, normalização de score, sistema linear e callbacks, estão explicadas junto de suas funções consumidoras. Os links e hashes são um retrato da versão documentada, não substituem uma nova leitura após alterações.

<!-- INVENTARIO_GERADO -->

## Inventário das declarações

| Arquivo | Função ou método | Guia principal |
| --- | --- | --- |
| [__init__.py](../__init__.py#L7) | `classFactory` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio.py](../Falhadeplantio.py#L15) | `FalhaDePlantioPlugin.__init__` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio.py](../Falhadeplantio.py#L18) | `FalhaDePlantioPlugin.initProcessing` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio.py](../Falhadeplantio.py#L23) | `FalhaDePlantioPlugin.initGui` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio.py](../Falhadeplantio.py#L26) | `FalhaDePlantioPlugin.unload` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio_provider.py](../Falhadeplantio_provider.py#L15) | `FalhaDePlantioProvider.__init__` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio_provider.py](../Falhadeplantio_provider.py#L18) | `FalhaDePlantioProvider.unload` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio_provider.py](../Falhadeplantio_provider.py#L21) | `FalhaDePlantioProvider.loadAlgorithms` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio_provider.py](../Falhadeplantio_provider.py#L25) | `FalhaDePlantioProvider.id` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio_provider.py](../Falhadeplantio_provider.py#L28) | `FalhaDePlantioProvider.name` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio_provider.py](../Falhadeplantio_provider.py#L31) | `FalhaDePlantioProvider.icon` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio_provider.py](../Falhadeplantio_provider.py#L35) | `FalhaDePlantioProvider.longName` | [Explicação](00_ARQUITETURA_E_FLUXO.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L56) | `FalhaDePlantioAlgorithm.initAlgorithm` | [Explicação](01_ENTRADAS_PARAMETROS_CRS.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L118) | `FalhaDePlantioAlgorithm.processAlgorithm` | [Explicação](03_CLASSIFICACAO_RGB.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L567) | `FalhaDePlantioAlgorithm._warp_progress` | [Explicação](02_PREPARACAO_RECORTE_RASTER.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L571) | `FalhaDePlantioAlgorithm._prepare_cutline` | [Explicação](02_PREPARACAO_RECORTE_RASTER.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L626) | `FalhaDePlantioAlgorithm._classify_window` | [Explicação](03_CLASSIFICACAO_RGB.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L752) | `FalhaDePlantioAlgorithm._estimate_metric_pixel_size` | [Explicação](02_PREPARACAO_RECORTE_RASTER.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L760) | `FalhaDePlantioAlgorithm.name` | [Explicação](03_CLASSIFICACAO_RGB.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L763) | `FalhaDePlantioAlgorithm.displayName` | [Explicação](03_CLASSIFICACAO_RGB.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L766) | `FalhaDePlantioAlgorithm.group` | [Explicação](03_CLASSIFICACAO_RGB.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L769) | `FalhaDePlantioAlgorithm.groupId` | [Explicação](03_CLASSIFICACAO_RGB.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L772) | `FalhaDePlantioAlgorithm.createInstance` | [Explicação](03_CLASSIFICACAO_RGB.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L775) | `FalhaDePlantioAlgorithm.shortHelpString` | [Explicação](03_CLASSIFICACAO_RGB.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L803) | `FalhaDePlantioAlgorithm.helpUrl` | [Explicação](03_CLASSIFICACAO_RGB.md) |
| [Falhadeplantio_algorithm.py](../Falhadeplantio_algorithm.py#L806) | `FalhaDePlantioAlgorithm._local_utm_crs` | [Explicação](01_ENTRADAS_PARAMETROS_CRS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L55) | `RestituirLinhasAlgorithm.initAlgorithm` | [Explicação](01_ENTRADAS_PARAMETROS_CRS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L142) | `RestituirLinhasAlgorithm.processAlgorithm` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L484) | `RestituirLinhasAlgorithm._accumulate_points_grid` | [Explicação](05_GRADES_FUSAO_ORIENTACAO.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L516) | `RestituirLinhasAlgorithm._splat_points` | [Explicação](05_GRADES_FUSAO_ORIENTACAO.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L525) | `RestituirLinhasAlgorithm._extract_raster_crop_grid` | [Explicação](05_GRADES_FUSAO_ORIENTACAO.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L589) | `RestituirLinhasAlgorithm._classify_rgb_grid` | [Explicação](05_GRADES_FUSAO_ORIENTACAO.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L637) | `RestituirLinhasAlgorithm._fuse_point_and_raster_density` | [Explicação](05_GRADES_FUSAO_ORIENTACAO.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L658) | `RestituirLinhasAlgorithm._build_local_orientation_field` | [Explicação](05_GRADES_FUSAO_ORIENTACAO.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L746) | `RestituirLinhasAlgorithm._steerable_ridge_filter_tiled` | [Explicação](05_GRADES_FUSAO_ORIENTACAO.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L826) | `RestituirLinhasAlgorithm._trace_rows_and_gaps` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1077) | `RestituirLinhasAlgorithm._smooth_or_straighten_grid_line` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1114) | `RestituirLinhasAlgorithm._remeasure_gaps` | [Explicação](10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1166) | `RestituirLinhasAlgorithm._measure_line_gaps` | [Explicação](10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1181) | `RestituirLinhasAlgorithm._reconstruct_from_planned_lines` | [Explicação](07_CENTROS_E_AJUSTE.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1404) | `RestituirLinhasAlgorithm._offsets_from_plant_centers` | [Explicação](07_CENTROS_E_AJUSTE.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1491) | `RestituirLinhasAlgorithm._extract_planned_polylines` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1523) | `RestituirLinhasAlgorithm._resample_and_smooth_planned_line` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1580) | `RestituirLinhasAlgorithm.name` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1583) | `RestituirLinhasAlgorithm.displayName` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1586) | `RestituirLinhasAlgorithm.group` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1589) | `RestituirLinhasAlgorithm.groupId` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1592) | `RestituirLinhasAlgorithm.createInstance` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [RestituirLinhasAlgorithm.py](../RestituirLinhasAlgorithm.py#L1595) | `RestituirLinhasAlgorithm.shortHelpString` | [Explicação](06_RASTREAMENTO_DAS_LINHAS.md) |
| [cane_centers.py](../cane_centers.py#L29) | `row_context_support` | [Explicação](07_CENTROS_E_AJUSTE.md) |
| [cane_centers.py](../cane_centers.py#L83) | `fit_center_offsets` | [Explicação](07_CENTROS_E_AJUSTE.md) |
| [cane_centers.py](../cane_centers.py#L190) | `chromatic_exg` | [Explicação](07_CENTROS_E_AJUSTE.md) |
| [cane_centers.py](../cane_centers.py#L198) | `_otsu` | [Explicação](07_CENTROS_E_AJUSTE.md) |
| [cane_centers.py](../cane_centers.py#L219) | `_disk` | [Explicação](07_CENTROS_E_AJUSTE.md) |
| [cane_centers.py](../cane_centers.py#L225) | `stool_center_score` | [Explicação](07_CENTROS_E_AJUSTE.md) |
| [cane_centers.py](../cane_centers.py#L300) | `local_maxima_centers` | [Explicação](07_CENTROS_E_AJUSTE.md) |
| [cane_centers.py](../cane_centers.py#L327) | `detect_stool_centers` | [Explicação](07_CENTROS_E_AJUSTE.md) |
| [planting_gaps.py](../planting_gaps.py#L13) | `intervals_from_states` | [Explicação](10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md) |
| [planting_gaps.py](../planting_gaps.py#L45) | `local_positive_quantile` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [planting_gaps.py](../planting_gaps.py#L62) | `_metric_disk` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [planting_gaps.py](../planting_gaps.py#L68) | `bounded_visible_absence` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [planting_gaps.py](../planting_gaps.py#L89) | `plant_body_pixels` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [planting_gaps.py](../planting_gaps.py#L125) | `visible_soil_support` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [planting_gaps.py](../planting_gaps.py#L147) | `classify_cross_sections` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [planting_gaps.py](../planting_gaps.py#L290) | `sample_polyline` | [Explicação](10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md) |
| [planting_gaps.py](../planting_gaps.py#L315) | `review_intervals` | [Explicação](10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md) |
| [planting_gaps.py](../planting_gaps.py#L323) | `segment_coordinates` | [Explicação](10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md) |
| [planting_gaps.py](../planting_gaps.py#L333) | `GapRasterSampler.__init__` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [planting_gaps.py](../planting_gaps.py#L361) | `GapRasterSampler._native_sample` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [planting_gaps.py](../planting_gaps.py#L393) | `GapRasterSampler.valid_points` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [planting_gaps.py](../planting_gaps.py#L398) | `GapRasterSampler.states` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [planting_gaps.py](../planting_gaps.py#L463) | `GapRasterSampler.close` | [Explicação](09_IDENTIFICACAO_DE_FALHAS.md) |
| [row_network.py](../row_network.py#L12) | `stationing` | [Explicação](08_CONTINUIDADE_E_PROJECOES.md) |
| [row_network.py](../row_network.py#L17) | `clip_native` | [Explicação](08_CONTINUIDADE_E_PROJECOES.md) |
| [row_network.py](../row_network.py#L47) | `connect_observed_fragments` | [Explicação](08_CONTINUIDADE_E_PROJECOES.md) |
| [row_network.py](../row_network.py#L134) | `complete_network` | [Explicação](08_CONTINUIDADE_E_PROJECOES.md) |
| [row_network.py](../row_network.py#L168) | `_complete_parallel_network` | [Explicação](08_CONTINUIDADE_E_PROJECOES.md) |
| [row_network.py](../row_network.py#L291) | `register_empty_rows` | [Explicação](08_CONTINUIDADE_E_PROJECOES.md) |

## Assinaturas dos arquivos documentados

| Arquivo | SHA-256 |
| --- | --- |
| `__init__.py` | `ba70551efdfd29b1405f87fe3645c4263ad3065a544682abab3335402bd08e46` |
| `Falhadeplantio.py` | `e97dcd9d82247b6f005313d4dd2948f5568a3dd36c27760130373faa0e9ac1de` |
| `Falhadeplantio_provider.py` | `4990bbbf9f827cc40217d9bf058b012f8f8133f18ac897875f0f98d4fd014efe` |
| `Falhadeplantio_algorithm.py` | `0beb94f780b4befb261546a4fa47d63abaaa5997523815a87ffc30fc6177ee4a` |
| `RestituirLinhasAlgorithm.py` | `78ce91b7dfa17c0cb7e2683b58a6070ba7e2a2ad834cfba0c0c403ed60e6f283` |
| `cane_centers.py` | `e9a8bdc2ca52a32ed9002e07650356efd0869104762b1d972267816d4c1da352` |
| `planting_gaps.py` | `2bcd785e69f280b0953fe85ee1bb1022c7a9034a04244719f7429abbd5597743` |
| `row_network.py` | `8790bc00740d7cc2df876ff07b3efd50996ef0ed27e6a4fdf202c6f7554462e6` |
