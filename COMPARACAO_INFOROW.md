# Nova comparação com Inforow — revisão 2.4.1

Data: 5 de novembro de 2026. Mínimo principal: **50 cm** em ambas as saídas.

## Conclusão

**Neste recorte, o Inforow parece mais completo na identificação de intervalos curtos visualmente plausíveis entre touceiras. Nosso plugin também identifica ausências plausíveis omitidas por ele, especialmente em trechos longos e nas extremidades.** A amostra não permite declarar um vencedor global em acurácia nem confirmar botanicamente cada marcação.

Foi encontrado e corrigido um erro reproduzível no nosso classificador: as mesmas coordenadas podiam mudar de classe quando variava o sentido de leitura dos blocos. A correção foi validada independentemente da concordância com o Inforow. Ela não resolveu as divergências visuais selecionadas, nem foi usada para igualar contagens entre ferramentas.

## Comparação equivalente

- Nova geração completa com o código do commit-base `b7b3b3452bc7ac863d6bdd018bdbe47150280b29`, seguida de nova geração com a correção local 2.4.1.
- Mesmo ortomosaico RGB, nuvem de pontos, linhas projetadas e mínimo de 50 cm.
- Geometrias transformadas para EPSG:31982 e recortadas à interseção do polígono do talhão com a cobertura válida nativa do RGB. Área comum: aproximadamente 78.970,04 m².
- O footprint foi calculado sem o limite padrão de 100 vértices do GDAL. Cada fragmento conectado resultante do recorte foi filtrado pelo mínimo de 50 cm.
- O Inforow foi tratado como outra saída a comparar, não como verdade de campo.

| Camada na área comum | Segmentos >= 50 cm | Comprimento | Segmentos >= 1,5 m |
| --- | ---: | ---: | ---: |
| Plugin 2.4, nova geração antes da correção | 3.419 | 3.835,34 m | 521 |
| Plugin corrigido, 2.4.1 | 3.319 | 3.757,94 m | 519 |
| Inforow | 5.015 | 4.904,04 m | 536 |

O Inforow contém 5.016 feições na fonte; uma fica fora do conjunto elegível após o recorte. Foram excluídos aproximadamente 4,59 m de sua geometria e 0,22 m da nossa por ficarem fora da área comum.

Com corredor lateral de **30 cm**:

| Concordância de comprimento | Plugin 2.4 | Plugin 2.4.1 |
| --- | ---: | ---: |
| Comprimento do plugin coberto por falhas do Inforow | 73,83% | 74,13% |
| Comprimento do Inforow coberto por falhas do plugin | 62,61% | 61,73% |

Esses percentuais são concordância geométrica, não precisão ou recall de campo. Um sentido aumentou e o outro caiu; a correção não demonstra melhora global de acurácia apenas por esses números. A diminuição de 100 segmentos também não prova que todos eram falsos positivos.

## Inspeção visual

Foram sorteadas **24 amostras**, com semente 20261105, distribuídas entre marcações exclusivas curtas, exclusivas longas e compartilhadas. Foi imposta separação espacial entre amostras. As imagens mostraram o segmento sem identificar a ferramenta; a avaliação foi registrada antes de abrir a chave de origem.

| Grupo inspecionado | Ausência visível plausível | Ambígua |
| --- | ---: | ---: |
| Exclusivas do plugin | 7 | 2 |
| Exclusivas do Inforow | 8 | 1 |
| Compartilhadas | 6 | 0 |

O avaliador foi o próprio assistente responsável pelo desenvolvimento. Os rótulos descrevem plausibilidade visual no RGB, não medição independente de colmos. A amostragem é pequena, estratificada e orientada às divergências; as proporções não estimam a precisão global das ferramentas.

As três amostras ambíguas incluem folhagem sobre parte do intervalo e limites incertos da ausência. Não foram automaticamente declaradas erros do programa correspondente. As mesmas 24 geometrias foram conferidas após a correção; suas divergências permaneceram essencialmente iguais. Portanto, o problema de sensibilidade às falhas curtas continua merecendo validação específica com limites de falha conferidos manualmente ou em campo.

## Erro reproduzido e corrigido

A largura típica da cultura era estimada por objeto no bloco de processamento inteiro. Uma seção larga do mesmo objeto podia mudar o tratamento de uma seção estreita distante, e a mudança do sentido de leitura mudava a partição desse objeto.

- Em 20 linhas reais sorteadas, quatro estações mudaram entre leitura direta e inversa das mesmas coordenadas: 20 cm somados. Nenhuma geometria ou fase de amostragem foi alterada nesse controle.
- Um raster sintético de cultura contínua com largura variável reproduziu a falha na versão congelada do commit-base: 256 das 800 estações diferiram entre os sentidos. A regra também podia tratar a seção estreita como ausência/incerteza por causa de cultura mais larga distante.
- A largura passou a ser estimada em uma janela física local de 1 m. O halo passou a cobrir essa janela, o crescimento limitado e o suporte de área proporcional à resolução.
- O número de amostras transversais passou a incluir corretamente as extremidades dos intervalos, mantendo passo igual ou menor ao pixel nativo.
- Após a correção: zero divergências nas mesmas coordenadas das 20 linhas, controle sintético aprovado, **69 testes de regressão aprovados** e **nove cenários completos aprovados com os critérios originais**.

O controle congelado anterior continua disponível com resultado reprovado esperado, permitindo reproduzir o antes/depois. As verdades e as tolerâncias dos ensaios de aceitação não foram relaxadas.

## Execução corrigida e auditoria

- Tempo completo: 173,3 s antes e 179,3 s depois, incluindo reconstrução, medição e gravação.
- 234 linhas; suas geometrias são idênticas antes/depois, conferidas por hash das geometrias.
- 3.319 segmentos, somando 3.758,16 m antes do recorte da comparação.
- Zero geometrias inválidas, zero pares de linhas cruzadas e zero falhas fora de sua linha associada na tolerância da auditoria.
- Menor falha: aproximadamente 50 cm.
- 563,11 m incertos e 48,69 m sem dados, mantidos separados das falhas confirmadas.

O grupo **Comparação — plugin 2.4.1 e Inforow** foi adicionado ao QGIS com as camadas comparáveis e as 24 amostras de inspeção. As camadas anteriores foram preservadas. A instalação do perfil não foi substituída; os testes usaram o código local corrigido.

## Evidências e reprodução

As evidências do conjunto real ficam fora do código do plugin, em `validacao_centros/comparacao_2_4_inforow_20261105`, incluindo:

- `input_manifest.json`, parâmetros e hashes da nova geração;
- `comparison.json` e `fixed/comparison.json`, métricas comparáveis antes/depois;
- `blind_contact_0.png`, `blind_contact_1.png` e imagens individuais;
- `blind_annotations.json` e `blind_samples_key.json`, avaliação e chave de origem;
- `same_sample_after_fix.json`, acompanhamento da mesma amostra;
- `direction_audit.json`, `direction_audit_after.json` e `regression_before_fix.txt`;
- `acceptance_fixed`, 69 regressões e os nove cenários completos;
- `fixed`, saídas corrigidas e auditoria geométrica.

O teste `test_variable_width_objects_are_independent_of_block_read_direction` está no repositório. A aprovação de testes verifica as propriedades ensaiadas; não transforma concordância com o Inforow em certificação agronômica.
