# Laudo de aceitação funcional — revisão 2.4

Data: 5 de novembro de 2026.

**Revisão 2.6, de 6 de novembro:** os testes de ausências longas, cultura deslocada, NoData e continuidade automática foram ampliados. Diagnóstico, execução reproduzível e limites estão em [AUDITORIA_FALHAS_2_6.md](AUDITORIA_FALHAS_2_6.md). Os resultados históricos abaixo continuam identificados por revisão.

**Atualização 2.5:** a bateria de regressão ampliada passou por **75 testes**, incluindo o fluxo completo de uma falha de 50 cm atravessada por folha lateral, preservação das geometrias e controles de plantas deslocadas. Método, reprodução e limites estão em [FALHAS_CURTAS.md](FALHAS_CURTAS.md). Os resultados históricos abaixo identificam suas respectivas revisões; não devem ser atribuídos automaticamente à 2.5.

**Parecer: os nove cenários da bateria de aceitação foram aprovados após a reestruturação, com os mesmos critérios de geometria, correspondência, mínimo de 50 cm e erro de comprimento.**

Base: commit `b215d7340e7956ab76fcd20a379a589fc156aa03` acrescido das alterações locais da revisão 2.4. O manifesto identifica os cinco módulos de produção por SHA-256. A instalação precisa conter os arquivos testados; a mesma versão nominal não identifica por si só a implementação.

## Execução e critérios

- **68 testes de regressão aprovados**, sem erros, falhas ou testes ignorados.
- **Nove cenários completos aprovados**, executando o código de produção do RGB à classificação, nuvem, restituição e medição. A restituição não foi substituída por geometrias simuladas.
- Execução completa no talhão real, em segundo plano, sem substituir as camadas anteriores.
- Ambiente: QGIS 3.44.11, Python 3.12.13 e GDAL 3.13.0 no Windows.

Os ensaios sintéticos têm cinco fileiras, espaçamento de 1,5 m e pixel de 5 cm. Nos cenários com falhas, há oito ausências definidas antes de executar o plugin: uma próxima de 50 cm, outras maiores, falha inicial e uma fileira totalmente vazia. Há uma fileira totalmente plantada de controle. O cenário automático saudável tem cinco fileiras plantadas sem falhas.

Foram preservados os critérios originais: geometrias válidas, ausência de cruzamentos/duplicações, uma linha por fileira, pelo menos 95% de cada referência coberta a até 10 cm, correspondência de todas as falhas (inclusive a próxima de 50 cm), nenhuma previsão sem correspondência, erro máximo de comprimento de 10 cm e respeito ao mínimo de 50 cm. Permanece apenas a tolerância numérica original de ponto flutuante de 0,000001 m.

O pareamento individual usa corredor de 10 cm e pelo menos 70% de sobreposição em ambos os comprimentos. São convenções técnicas desta bateria, não uma norma agronômica. A verdade geométrica, o mínimo e as tolerâncias não foram alterados para obter aprovação. O teste antigo que esperava a ausência de uma fileira foi fortalecido para exigir cinco, origem explícita da inferência e aprovação de todos os critérios.

## Resultados

| Cenário | Linhas / esperadas | Falhas correspondentes / esperadas | Resultado |
| --- | ---: | ---: | --- |
| Tiro reto com projeto alinhado | 5/5 | 8/8 | Aprovado |
| Projeto deslocado 15 cm | 5/5 | 8/8 | Aprovado |
| Curva de nível com projeto | 5/5 | 8/8 | Aprovado |
| Direção oblíqua de 33° com projeto | 5/5 | 8/8 | Aprovado |
| Cana moderadamente amarelada com projeto | 5/5 | 8/8 | Aprovado |
| Automático, tiro reto com falhas | 5/5 | 8/8 | Aprovado |
| Automático, cinco fileiras saudáveis | 5/5 | 0/0 | Aprovado |
| Automático, direção oblíqua com falhas | 5/5 | 8/8 | Aprovado |
| Automático, curva com falhas | 5/5 | 8/8 | Aprovado |

Maior erro de comprimento: aproximadamente **7,17 cm**, dentro do limite de 10 cm. A aprovação espacial exige 95% do comprimento dentro do corredor de 10 cm; não exige erro inferior a 10 cm em todo ponto sem exceção. O manifesto conserva os desvios máximos e percentis.

O resultado 9/9 não é uma estimativa estatística de acurácia nos talhões do usuário. Os casos foram construídos para testar requisitos e corrigir as reprovações anteriores.

## Correções e controles

1. **Mínimo e bordas de plantas:** amostras nativas substituem a mistura bilinear seguida de crescimento de cor fraca. O apoio transversal é adaptado a cada objeto, reduzindo a influência de suas bordas parciais sem impor a largura de uma touceira grande às pequenas isoladas. O mínimo não foi reduzido; plantas confirmadas interrompem a ausência.
2. **Bordas da imagem:** o recorte usa a máscara nativa e refina sua transição. A linha não precisa terminar no vértice anterior da grade de 25 cm. A perda de aproximadamente 25 cm da falha total oblíqua foi reduzida para menos de 3 cm.
3. **Projeto deslocado:** um registro comum pequeno, confirmado por pelo menos três fileiras apoiadas por cultura e com resíduos limitados, pode ser transferido às fileiras sem apoio próprio. A origem é `projeto_registrado`. Sem consenso, preserva-se a referência; uma mancha isolada não desloca as demais.
4. **Sementes automáticas:** máximos das cristas substituem a grade fixa que podia ignorar fileiras inteiras. O cálculo em faixas com halo limita a memória adicional.
5. **Continuidade e curva:** após refinar as fileiras observadas, o modelo de vizinhança usa somente apoio aceito para melhorar trechos protegidos e extremidades, com extensão limitada e recorte pela imagem. Uma fileira vazia só é inferida entre vizinhas paralelas, com espaçamento regular, sobreposição suficiente e controle de duplicações. Não são criadas fileiras além das externas observadas. A origem `inferida_entre_vizinhas` explicita a hipótese geométrica.
6. **Recusas verificadas:** espaçamento irregular, direções incompatíveis, sobreposição curta, criação de fileiras externas/duplicadas e registro com apenas uma fileira apoiada. Esses controles passaram; não abrangem todas as configurações possíveis.

## Talhão real

O fluxo completo com linhas projetadas e mínimo de 50 cm terminou em **178,4 s**, incluindo gravação. Auditoria:

- 234 linhas e 3.419 segmentos de falha;
- zero geometrias inválidas, zero pares de linhas cruzadas e zero falhas fora da linha associada na tolerância da auditoria;
- menor falha de aproximadamente 50 cm;
- 3.835,56 m de falhas, 567,06 m incertos e 48,69 m sem dados;
- 4.482 trechos de revisão;
- todas as 234 linhas com origem `projeto`: não houve transferência de registro nem inferência automática nessa execução com projeto.

Resultados carregados no grupo **Validação 2.4 — resultados reestruturados**, preservando as camadas anteriores. O perfil instalado do QGIS não foi substituído: a execução usou o código local de validação. Essa rodada confirma integridade e execução no conjunto real. O aumento de segmentos não comprova maior acurácia agronômica; faltam rótulos independentes de campo para certificar cada falha e cada centro de touceira.

## Reproduzir

Execute no console Python de um QGIS inicializado, sem abrir uma segunda QApplication ou um processo Python do QGIS por fora:

```python
import importlib.util
from pathlib import Path
repo = Path(r"CAMINHO_DO_REPOSITORIO")
output = Path(r"PASTA_NOVA_PARA_RESULTADOS")
spec = importlib.util.spec_from_file_location("acceptance", repo / "scripts/validate_acceptance_qgis.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)
print(acceptance.run_regressions(output))
# Um cenário por chamada para manter o QGIS disponível entre etapas.
print(acceptance.run_case("automatic_contour", output))
# Os nove nomes estão em acceptance.CASES.
```

Cada cenário grava RGB, verdade geométrica, GeoPackages e métricas JSON. O identificador de importação inclui `row_network.py`, evitando reutilizar um módulo antigo em cache. Makefile e pb_tool incluem esse módulo no empacotamento.

## Alcance

**Aprovada a bateria funcional descrita, incluindo os casos anteriormente reprovados.** Não há comprovação independente para todas as variedades, estágios, iluminações ou invasoras. Cana amarelada foi verificada em ensaios de cor controlada; a semelhança visual com palhada e invasoras continua sujeita à incerteza do RGB. A geometria inferida depende da regularidade observada e do espaçamento informado.

Este é um laudo de testes reproduzíveis produzido junto ao desenvolvimento. Não é certificação independente de organismo acreditado nem garantia de identificação perfeita em qualquer imagem.

## Revisão posterior 2.4.1 — comparação com Inforow

Uma nova execução e inspeção estratificada de divergências com o Inforow identificaram uma dependência de processamento que não estava coberta na bateria original. A largura típica de um objeto era calculada no bloco completo; variar o sentido de leitura podia mudar a classe das mesmas coordenadas. Nas 20 linhas reais sorteadas, quatro amostras (20 cm somados) mudaram de classe. Em um controle sintético com largura variável, 256 de 800 estações diferiam entre os sentidos.

O cálculo passou a usar uma janela física local, com halo suficiente para largura, crescimento limitado e área de ambiguidade. O número de amostras transversais foi corrigido para manter passo igual ou menor ao pixel nativo. Após a correção, nenhuma das mesmas coordenadas das 20 linhas mudou de classe com a reversão. O novo controle sintético também passou.

**A revisão passou por 69 testes de regressão e manteve aprovação nos nove cenários completos, com os critérios originais.** Isso verifica a correção reproduzida e preserva as propriedades anteriores. Concordância com outro programa e inspeção visual de uma amostra pequena continuam sem equivaler a acurácia de campo. As métricas e imagens da comparação são conservadas separadamente dos dados de teste sintéticos.
