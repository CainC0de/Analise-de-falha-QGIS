# Documentação técnica do plugin Falha de Plantio

Esta documentação descreve a **implementação local da versão 2.6**, em 6 de novembro de 2026. Ela explica as operações executadas pelo código; os resultados de testes são apresentados separadamente. Uma regra implementada não equivale a uma garantia de acurácia agronômica.

## Ordem de leitura

| Documento | Conteúdo |
| --- | --- |
| [00 — Arquitetura e fluxo](00_ARQUITETURA_E_FLUXO.md) | Inicialização, módulos, dependências e sequência completa |
| [01 — Entradas, parâmetros e CRS](01_ENTRADAS_PARAMETROS_CRS.md) | Todas as entradas públicas, unidades, padrões e efeitos |
| [02 — Preparação e recorte](02_PREPARACAO_RECORTE_RASTER.md) | Bandas, projeção, resolução, máscara, VRT e validade |
| [03 — Classificação RGB](03_CLASSIFICACAO_RGB.md) | GLI, NGRDI, contraste adaptativo, palhada, sombra e manchas densas |
| [04 — Nuvem de pontos](04_NUVEM_DE_PONTOS.md) | Agregação espacial, centroides, filtros e atributos |
| [05 — Grades e orientação](05_GRADES_FUSAO_ORIENTACAO.md) | Fusão raster/pontos, FFT e filtros direcionais |
| [06 — Rastreamento das linhas](06_RASTREAMENTO_DAS_LINHAS.md) | Modo automático, modo com projeto, sementes e suavização |
| [07 — Centros e ajuste](07_CENTROS_E_AJUSTE.md) | Núcleos, votos de folhas, contexto e ajuste com limites geométricos |
| [08 — Continuidade e projeções](08_CONTINUIDADE_E_PROJECOES.md) | Ligações, famílias, inferência, cabeceiras, recorte e registro |
| [09 — Identificação de falhas](09_IDENTIFICACAO_DE_FALHAS.md) | Perfil RGB, presença, solo, incerteza, núcleos e ausências longas |
| [10 — Comprimentos e saídas](10_COMPRIMENTOS_CATEGORIAS_SAIDAS.md) | Mínimo, categorias, percentuais, geometrias e campos |
| [11 — Recursos e erros](11_RECURSOS_CANCELAMENTO_ERROS.md) | Blocos, memória, arquivos, cancelamento e diagnóstico |
| [12 — Testes e reprodução](12_TESTES_E_REPRODUCAO.md) | Bateria funcional, manifestos e comparação com outras ferramentas |
| [13 — Mapa do código](13_MAPA_DO_CODIGO.md) | Referência das funções e roteiro de manutenção |

## As distinções fundamentais

1. O raster temático identifica **cobertura verde**. O valor zero não é, sozinho, uma falha de plantio.
2. A nuvem contém **pontos 2D representativos de pixels de cultura**. Um ponto não equivale necessariamente a um pé de cana.
3. O traçado representa a **geometria estimada da fileira**. Uma linha pode atravessar ausência de cultura.
4. A falha final é um **intervalo de ausência apoiada no raster**, medido sobre a linha e filtrado pelo mínimo.
5. Os estados **incerto** e **sem dados** são diferentes de ausência confirmada.

## Fontes e escopo

Os links para arquivos Python abrem a implementação correspondente na raiz do repositório. Os nomes de funções são os pontos de busca estáveis; números de linha mudam com a manutenção.

Consulte também [README principal](../README.md), [auditoria 2.6](../AUDITORIA_FALHAS_2_6.md), [validação histórica](../VALIDACAO.md), [comparação 2.4.1 com Inforow](../COMPARACAO_INFOROW.md) e [método de falhas curtas 2.5](../FALHAS_CURTAS.md). Esses documentos históricos descrevem suas próprias revisões.

O catálogo não pressupõe um modelo de aprendizado de máquina treinado. Os classificadores atuais combinam índices, limiares, morfologia, estatística local e restrições geométricas. Dossel fechado, invasoras e colmos ocultos continuam sujeitos às limitações do RGB.
