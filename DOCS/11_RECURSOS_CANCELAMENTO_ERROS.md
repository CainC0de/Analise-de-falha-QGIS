# 11 — Recursos, arquivos temporários, cancelamento e erros

[Índice](README.md) · Fontes: os dois `processAlgorithm()`, [cane_centers.py](../cane_centers.py), [planting_gaps.py](../planting_gaps.py) e [row_network.py](../row_network.py).

## Onde há processamento em blocos

| Etapa | Estratégia |
| --- | --- |
| Classificação e pontos | Região interna próxima de 2048 pixels, alinhada à agregação; halo de contexto |
| Acumular pontos na grade | Lotes de 100.000 geometrias |
| Orientação | FFT em batches de patches de uma faixa de janelas |
| Filtros direcionais | Tiles internos de 1024 células com halo |
| Centros RGB | Blocos de 40 m com halo |
| Falhas | 256 ou 512 estações com halo; união da evidência no perfil completo |
| Leitura discreta do raster de falhas | Tiles 256 × 256 e LRU de 32 MiB |

O cache de 32 MiB limita **somente os tiles desse amostrador**. A grade de fusão, resposta direcional, coerência, coordenadas, sinks, cache GDAL e outras matrizes consomem memória adicional. O teto de 80 milhões de células por grade também não é um teto de memória total.

VRT é uma descrição virtual de acesso/reprojeção. Evita materializar certas imagens intermediárias, mas não impede que uma chamada `ReadAsArray()` carregue uma matriz inteira da grade analítica.

## Pastas transitórias e saídas persistentes

| Prefixo de `TemporaryDirectory` | Uso |
| --- | --- |
| `falha_plantio_rgb_` | VRT de bandas, reprojeção virtual e cutline |
| `restituir_grid_` | VRT da grade de fusão |
| `cane_centers_` | VRTs de blocos do detector de núcleos |
| `cane_native_footprint_` | Amostrador usado no primeiro recorte da geometria |
| `cane_row_network_` | Amostrador de validade da rede automática |
| `cane_gap_measurement_` | VRT e cache da medição final |

Os destinos de resultado são separados dessas estruturas transitórias. Sinks temporários e arquivos temporários gerados pelo Processing dependem do ciclo de vida do contexto/sessão QGIS; devem ser salvos quando se deseja preservá-los.

`GapRasterSampler.close()` solta o dataset e limpa os tiles. Blocos `finally` chamam esse fechamento nos consumidores. GeoPackages abertos podem ficar bloqueados pelo provedor no Windows; os testes evitam deixar conexões de leitura vivas durante a limpeza de suas pastas.

## Cancelamento

O código consulta `feedback.isCanceled()` entre blocos, lotes, linhas, etapas de rede e parte das operações de centro. O callback de Warp devolve falso quando cancelado. Os algoritmos principais retornam `{}` em vários desses pontos.

Não é uma transação com rollback: uma operação já enviada ao GDAL ou a um cálculo NumPy/SciPy pode terminar antes da próxima consulta. Arquivos parciais já abertos/criados podem continuar em disco. O retorno vazio não deve ser interpretado como conjunto completo de resultados válidos.

## Erros que interrompem a execução

Entre as condições recusadas estão raster/CRS inválido, bandas repetidas/inexistentes, máscara ausente no modo de recorte, geometria poligonal inválida, saída sobre o original, CRS não métrico da nuvem, extensões incompatíveis, ausência de pontos suficientes sem projeto, fileiras insuficientes e falhas de gravação de sinks.

Na restituição, pelo menos uma parte é necessária com projeto e pelo menos duas sem projeto. Isso não garante que cada parte corresponda a uma fileira agronômica válida.

## Fallbacks locais

| Situação | Comportamento implementado |
| --- | --- |
| Estimativa métrica de pixel falha na primeira ferramenta | Estimativa de 5 cm como fallback |
| Sinal raster da grade não pode ser extraído | Retornos `None`; fusão pode continuar com pontos |
| Detecção de centros RGB levanta `RuntimeError`/`ValueError` | Mensagem e uso do sinal da grade/nuvem |
| Referência isolada não pode ser transformada | Feição ignorada na extração |
| Não há apoio confiável para centralização | Deslocamento protegido na referência |
| Evidência RGB ambígua | Estado de revisão, separado de ausência |

Os fallbacks não têm todos o mesmo alcance. Uma falha global ao abrir o raster de medição final impede a operação; não autoriza reutilizar as falhas provisórias do rastreador como se fossem o resultado final.

## Diagnóstico por sintoma

| Sintoma | Conferência útil |
| --- | --- |
| Nuvem muito densa ou irregular | Resolução efetiva, espaçamento de agregação, limiar e manchas contínuas |
| Linha sai da cultura | Entrelinha, ordem física RGB, referência, sinal local e `pct_pes`/`pct_proj` |
| Não aparece uma linha em região vazia | Apoio para inferência entre vizinhas ou referência externa disponível |
| Cana parece falha | Alinhamento do eixo, RGB original, núcleos laterais e revisão |
| Falha visível não aparece | Mínimo, folhagem sobreposta, sombra, `incerto_m`, geometria ausente |
| Percentual baixo em área problemática | Conferir denominador avaliado e trechos incertos/NoData |
| Execução demora | Área/dimensões efetivas, densidade de pontos, quantidade de linhas, destino e acesso aos arquivos |

Uma mensagem de sucesso comprova conclusão do fluxo computacional, não valida cada identificação na imagem.
