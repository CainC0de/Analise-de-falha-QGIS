# 🌿 Falha de Plantio — Plugin QGIS

Plugin para QGIS (≥ 3.22) dedicado à **detecção automática de falhas de plantio** na cultura de **cana-de-açúcar**, utilizando imagens aéreas (drone ou satélite).

> **Código LIVRE** (GPL v2+) — Uso comercial proibido sem contribuição à comunidade open source.

---

## 📋 Funcionalidades

- **Detecção automática** de falhas ao longo das linhas de plantio
- **Dois índices de vegetação**: GLI (imagens RGB) e NDVI (imagens multibanda com NIR)
- **Threshold configurável** para ajustar a sensibilidade da detecção
- **Filtro de comprimento mínimo** para ignorar micro-falhas (ruído)
- **Estatísticas automáticas**: total de falhas, comprimento total/médio/máximo, percentual de falha
- Saída vetorial com atributo `comp_m` (comprimento em metros)

---

## 🚀 Instalação

### Via Plugin Manager do QGIS
1. Abra o QGIS
2. Vá em **Plugins → Gerenciar e Instalar Plugins**
3. Procure por **"Falha de Plantio"**
4. Clique em **Instalar**

### Instalação Manual
1. Baixe o repositório como `.zip`
2. No QGIS, vá em **Plugins → Gerenciar e Instalar Plugins → Instalar a partir de ZIP**
3. Selecione o arquivo `.zip` baixado

### Via Terminal (Linux)
```bash
# Clone o repositório na pasta de plugins do QGIS
cd ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
git clone https://github.com/CainC0de/Analise-de-falha-QGIS.git Falhadeplantio
```

---

## 🔧 Como Usar

O plugin é acessado via **Processing Toolbox** do QGIS:

1. Abra o **Processing Toolbox** (`Ctrl+Alt+T`)
2. Navegue até **Falha de Plantio → Análise → Falha de Plantio (Cana-de-açúcar)**
3. Configure os parâmetros:

| Parâmetro | Descrição | Padrão |
|---|---|---|
| **Raster** | Imagem RGB de drone/satélite (ou multibanda com NIR) | — |
| **Linhas de Plantio** | Camada vetorial de linhas representando as fileiras | — |
| **Contorno do Talhão** | Polígono delimitando a área de análise | — |
| **Índice de Vegetação** | GLI (RGB) ou NDVI (se tiver banda NIR) | GLI |
| **Limiar de Vegetação** | Valor mínimo do índice para considerar como planta | 0.0 |
| **Buffer do Contorno** | Expansão do contorno para evitar ruído nas bordas | 0.1 |
| **Comprimento Mínimo** | Falhas menores que este valor (m) são ignoradas | 0.5 |
| **Banda NIR** | Número da banda infravermelha (apenas para NDVI) | 4 |

   **Parâmetros de Performance** (otimização para imagens grandes):

| Parâmetro | Descrição | Padrão |
|---|---|---|
| **Sieve (anti-ruído)** | Remove grupos de pixels menores que N (elimina ruído raster) | 50 |
| **Resolução de Análise** | Reamostra para esta resolução em metros (0 = original) | 0.20 |
| **Tolerância de Simplificação** | Douglas-Peucker nos polígonos (reduz vértices) | 0.1 |

4. Clique em **Executar**

---

## 📊 Saídas

### Camada Vetorial
- **Linhas de falha**: cada segmento sem vegetação ao longo das linhas de plantio
- Atributo `comp_m`: comprimento da falha em metros

### Estatísticas (no log de processamento)
```
========== ESTATÍSTICAS DE FALHAS ==========
Total de falhas encontradas: 42
Comprimento total de falhas: 523.45 m
Comprimento médio por falha: 12.46 m
Maior falha encontrada:      38.72 m
Comprimento total de linhas: 4521.30 m
Percentual de falha:         11.58%
=============================================
```

---

## 🔬 Como Funciona

O plugin executa um pipeline de **16 passos** (otimizado para alta resolução):

1. **Buffer** no contorno do talhão (evita ruído nas bordas)
2. **Recorte** do raster pelo contorno com buffer
3. **Cálculo** do índice de vegetação (GLI ou NDVI)
4. **Máscara binária** — separa vegetação de solo (tipo Byte, 8× menos memória)
5. 🆕 **Sieve Filter** — remove grupos de pixels menores que N (anti-ruído)
6. 🆕 **Reamostragem** — reduz resolução para análise (ex: 5cm → 20cm = 16× menos pixels)
7. **Poligonização** — converte pixels em polígonos
8. **Extração** dos polígonos de vegetação
9. 🆕 **Dissolve** — funde polígonos adjacentes em poucos grandes polígonos
10. 🆕 **Simplificação** — Douglas-Peucker remove vértices desnecessários
11. **Recorte** das linhas de plantio pelo contorno
12. **Diferença** — subtrai vegetação das linhas → falhas
13. **Explosão** de geometrias multipartes
14. **Cálculo** do comprimento em metros
15. **Filtro** por comprimento mínimo
16. **Estatísticas** automáticas

### Índices de Vegetação

| Índice | Fórmula | Bandas Necessárias |
|---|---|---|
| **GLI** | `(2G - R - B) / (2G + R + B)` | RGB (3 bandas) |
| **NDVI** | `(NIR - R) / (NIR + R)` | NIR + Vermelho |

---

## 📁 Estrutura do Projeto

```
Falhadeplantio/
├── __init__.py                  # Ponto de entrada do plugin
├── Falhadeplantio.py            # Classe principal do plugin
├── Falhadeplantio_provider.py   # Provider do Processing Toolbox
├── Falhadeplantio_algorithm.py  # Algoritmo de análise (pipeline)
├── metadata.txt                 # Metadados do plugin
├── canaicone.png                # Ícone do plugin
├── plugin_upload.py             # Script de upload para plugins.qgis.org
├── Makefile                     # Build e deploy
├── pb_tool.cfg                  # Configuração do Plugin Builder Tool
├── pylintrc                     # Configuração do Pylint
├── help/                        # Documentação Sphinx
├── i18n/                        # Traduções
├── scripts/                     # Scripts auxiliares
└── test/                        # Testes unitários
```

---

## 🤝 Contribuição

Contribuições são bem-vindas! Para contribuir:

1. Faça um fork do repositório
2. Crie uma branch para sua feature (`git checkout -b feature/minha-feature`)
3. Commit suas alterações (`git commit -m 'Adiciona minha feature'`)
4. Push para a branch (`git push origin feature/minha-feature`)
5. Abra um Pull Request

---

## 📄 Licença

Este projeto está licenciado sob a **GNU General Public License v2** (ou posterior).
Veja o arquivo de licença para mais detalhes.

---

## 👤 Autor

**CainC0de** — [@CainC0de](https://github.com/CainC0de)

Apoie a comunidade open source! 🌱
