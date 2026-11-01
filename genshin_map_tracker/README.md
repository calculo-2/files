# Genshin Map Tracker

Lê a tela do Genshin Impact, descobre onde você está pelo minimapa e marca baús e
oculi no mapa interativo [appsample](https://genshin-impact-map.appsample.com/pt/),
aberto no Chrome do segundo monitor.

**Status:** Fase 1 de 6. Estrutura do projeto, captura da janela e recorte do minimapa.

## Regras de segurança (não negociáveis)

- A única fonte de dados é a captura de tela, como OBS ou compartilhamento do Discord.
- Não lê memória, não injeta DLL, não intercepta rede, não hooka DirectX e não altera arquivos do jogo.
- Não envia teclas, cliques nem nenhuma outra entrada ao jogo.
- Não desenha nada sobre o jogo: sem overlay.
- Não se anexa ao processo do jogo. Só consulta título e posição da janela, uma API (Interface de Programação de Aplicações) pública do Windows.
- Tudo roda localmente. Nenhuma captura sai do seu PC.

## Decisões tomadas

| Tema | Decisão |
|---|---|
| Interface | Sem overlay. Uma janela de console no 2º monitor mostra cada comando enviado ao mapa (Fase 3). |
| Mapa | Não há mapa próprio. O site appsample é controlado por Playwright num perfil do Chrome (Fases 3 e 4). |
| Resolução alvo | 1920x1080, tela cheia, jogo em PT-BR. As outras resoluções funcionam por escala relativa. |
| Captura | dxcam (Desktop Duplication do Windows), com mss como reserva. |

## Instalação (Windows)

1. Instale o Python 3.11 ou mais novo: <https://www.python.org/downloads/>. Marque **"Add python.exe to PATH"**.
   Para conferir, rode `py --version`.
2. Baixe o código, abra um terminal na pasta `genshin_map_tracker` e rode:

```
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Teste da Fase 1

Com o jogo aberto em 1920x1080, tela cheia:

```
gmt find-window
```
Deve mostrar `Jogo encontrado` e `Área de captura: 1920x1080`.

```
gmt capture --seconds 20
```
Você tem 5 segundos para voltar ao jogo. Ande um pouco. No fim aparece um resumo com
quadros, FPS (Quadros Por Segundo) real e CPU (Unidade Central de Processamento).
Os arquivos ficam em `out\<data-hora>\`:

- `minimap\` – círculo do minimapa recortado, com fundo transparente e centro (seta) removido
- `frames\` – um quadro inteiro a cada 10
- `debug\` – quadro com o círculo detectado desenhado em verde

```
gmt capture --seconds 30 --no-save
```
Mede a CPU real, sem o custo de salvar PNG.

```
gmt calibrate print1.png print2.png print3.png
```
Acha o centro do minimapa pela seta do jogador, que fica sempre no centro dele.
Use de 3 a 5 prints com o personagem virado para lados diferentes. Se o círculo
verde em `_calibrate.png` bater, copie `config.example.toml` para `config.toml` e
cole os valores sugeridos. Em 1920x1080 isso já vem calibrado.

```
gmt crop caminho\do\print.png
```
Recorta o minimapa de qualquer print, sem o jogo aberto.

### O que me mandar de volta

1. A saída de `gmt find-window` e o resumo de `gmt capture --no-save`.
2. De 3 a 5 imagens de `debug\` e de `minimap\`.
3. De 5 a 10 prints em tela cheia (tecla Print Screen do Windows, não a câmera do jogo):
   cidade, campo aberto, à noite, debaixo d'água em Fontaine, um subterrâneo (Chasm
   ou Sumeru) e a tela com a notificação de baú aberto e de oculus coletado.
   Coloque-os em `tests\fixtures\`.

### Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `Jogo NÃO encontrado` | Jogo fechado ou título diferente | Abra o jogo; me mande o título da janela |
| Todos os quadros pretos | Captura bloqueada em tela cheia exclusiva | `--backend dxcam`, ou use janela sem borda |
| Círculo verde deslocado | Escala do Windows ou resolução diferente | Rode `gmt calibrate` com 3 a 5 prints |
| `Pulados` alto | Jogo fora de foco | A captura pausa sozinha quando o jogo não está em foco, para poupar CPU |

## Desenvolvimento

```
pytest           # testes (rodam também em Linux/macOS com quadros sintéticos)
ruff check .     # lint
mypy src         # tipos
```

### Estrutura

```
src/gmt/
  config.py            configuração (config.toml)
  logging_setup.py     logs
  cli.py               comandos gmt
  capture/
    window.py          acha a janela do jogo (só título/posição)
    backends.py        dxcam e mss
    grabber.py         laço com limite de FPS, medição de CPU, pausa fora de foco
  vision/
    regions.py         regiões relativas à resolução (base 1920x1080)
    minimap.py         recorte, máscara circular, seta do jogador, calibração
tests/                 testes automatizados
```

## Próximas fases

2. Localização no mapa completo por feature matching (correspondência de pontos característicos), com testes de precisão.
3. Playwright controlando o appsample (centralizar e seguir), mais o console de comandos no 2º monitor.
4. Leitura dos marcadores do site, conversão de coordenadas e calibração por Pontos de Teletransporte.
5. Detecção de coleta por OCR (Reconhecimento Óptico de Caracteres) em PT-BR e progresso em SQLite.
6. Configurações, atalho global de pausa, executável (PyInstaller) e README final.

## Limitações atuais

- Minimapa calibrado em 1920x1080 com prints reais: centro (169, 125), raio 100. As outras resoluções usam escala e ainda não foram testadas.
- Captura validada no Windows com mss: 5 FPS e cerca de 10% de um núcleo de CPU. O dxcam, que deve gastar menos, ainda precisa ser confirmado.
