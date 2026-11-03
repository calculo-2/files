# Genshin Map Tracker

Lê a tela do Genshin Impact, descobre onde você está pelo minimapa e marca baús e
oculi no mapa interativo [appsample](https://genshin-impact-map.appsample.com/pt/),
aberto no Chrome do segundo monitor.

**Status:** Fase 2 de 6. Localização no mapa pronta e testada com mapa sintético; falta o mapa base real (ver "Fonte do mapa base").

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
| Localização | Busca global por SIFT + RANSAC, confirmada por correlação de imagem; rastreio local por correlação; filtro de Kalman. |
| Mapa base | Proposta: o próprio mapa do appsample, para as coordenadas já saírem no sistema do site. Depende do `site-probe` e dos termos de uso. |

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

## Fase 2: localização no mapa

### Como funciona
1. **Busca global** (início, posição perdida, teleporte): pontos SIFT do minimapa (ampliado 2x)
   são comparados com os do mapa inteiro. O RANSAC acha a transformação; ela só é aceita se a
   rotação for perto de zero (o minimapa é norte-para-cima) e a escala for coerente. Depois, uma
   correlação de imagem independente confirma e refina a posição.
2. **Rastreio local** (a cada quadro): correlação do minimapa numa janela em volta da posição
   prevista. Rápido (cerca de 3 ms por quadro).
3. **Filtro de Kalman** suaviza a posição. Saltos impossíveis são descartados, a menos que se
   repitam (teleporte confirmado em 2 quadros).
4. **Camadas**: cada mapa base (Teyvat, subterrâneos etc.) é uma camada; o localizador informa
   em qual está. Basta passar um `--map` por camada.
5. **Confiança** de 0 a 1 em cada quadro. Depois de 5 falhas seguidas: "POSIÇÃO PERDIDA".

### Precisão medida (testes automáticos, mapa sintético)
| Medida | Resultado |
|---|---|
| Busca global: acerto | ~95% das posições na primeira tentativa |
| Busca global: erro | médio 0,3 px, máximo 1 px do mapa |
| Rastreio local: erro | médio 0,3 px do mapa |
| Tempo | global ~20 ms, local ~3 ms por quadro |

O mapa sintético tem menos detalhes que o real; os números reais serão medidos com o mapa do jogo.

### Comandos
```
gmt build-index mapa.png                     # pré-calcula os pontos (uma vez; cria mapa.png.index.npz)
gmt locate --map mapa.png print1.png ...     # localiza prints inteiros ou minimapas salvos
gmt track --map mapa.png                     # rastreio ao vivo; mostra a posição no console
```
Camadas: repita `--map` (ex.: `--map teyvat.png --map chasm.png`).

### Fonte do mapa base
Não existe mapa de Teyvat com licença realmente aberta: todos derivam das imagens do jogo
(propriedade da HoYoverse). O que foi avaliado:

| Fonte | Licença | Situação |
|---|---|---|
| Mapa do appsample | Termos ainda não lidos | **Proposta.** Coordenadas já no sistema do site. Depende do `site-probe`. |
| MrPowley/genshin-map-tracker | GPL-3.0 | Mesma ideia (SIFT). O mapa fica num Google Drive, sem licença própria. Só referência. |
| Hektin/Genshin-Chests | MIT | 3.328 baús com coordenadas do jogo. Possível referência de dados. |
| YuehaiTeam/zhiqiong | sem licença | Usa DLL fechada (cvAutoTrack). Descartado: não dá para auditar. |
| BetterGI | GPL-3.0 | Automação de gameplay, contra as regras do projeto. Descartado. |

### Diagnóstico do site (`site-probe`)
Abre o appsample uma vez, num perfil de Chrome só do gmt, e salva um relatório: biblioteca do
mapa, endereços dos blocos de imagem do mapa, dados de marcadores, chaves de progresso salvas
no navegador, `robots.txt` e páginas de termos de uso. Não faz login, não clica em nada e não
baixa o mapa inteiro. O relatório fica em `out\site_probe\`.

```
pip install -e ".[web]"
gmt site-probe
```
Se aparecer erro de navegador, rode `python -m playwright install chromium` e repita.

### Pendências da Fase 2
- Mapa base real (depende do `site-probe` e dos termos de uso).
- Medir a precisão com o mapa real e minimapas reais (`gmt capture` + `gmt locate`).
- Direção do jogador: a seta é quase um triângulo equilátero; a ponta só se distingue pelo
  sombreado. Precisa de capturas reais com direção conhecida.
- Mapas das camadas subterrâneas.

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
  localization/
    mapindex.py        mapa base + pontos SIFT em cache
    localizer.py       busca global, rastreio local, saltos, camadas, confiança
    tracking.py        filtro de Kalman
  web/
    probe.py           diagnóstico do site do mapa
tests/                 testes automatizados (synthetic.py gera mapa e minimapas falsos)
```

## Próximas fases

3. Playwright controlando o appsample (centralizar e seguir), mais o console de comandos no 2º monitor.
4. Leitura dos marcadores do site, conversão de coordenadas e calibração por Pontos de Teletransporte.
5. Detecção de coleta por OCR (Reconhecimento Óptico de Caracteres) em PT-BR e progresso em SQLite.
6. Configurações, atalho global de pausa, executável (PyInstaller) e README final.

## Limitações atuais

- Minimapa calibrado em 1920x1080 com prints reais: centro (169, 125), raio 100. As outras resoluções usam escala e ainda não foram testadas.
- Localização testada só com mapa sintético até agora.
- Captura validada no Windows com mss: 5 FPS e cerca de 10% de um núcleo de CPU. O dxcam, que deve gastar menos, ainda precisa ser confirmado.
