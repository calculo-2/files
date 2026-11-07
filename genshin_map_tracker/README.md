# Genshin Map Tracker

Lê a tela do Genshin Impact, descobre onde você está pelo minimapa e controla o mapa
interativo [appsample](https://genshin-impact-map.appsample.com/pt/) no Chrome do segundo
monitor: o mapa segue você, e baús e oculi coletados são marcados (ou sugeridos para você
confirmar).

**Estado:** o código das 6 fases está escrito e tem 94 testes automáticos. O que depende do seu
PC, do jogo e do site ainda não foi validado. Detalhes em [AVALIACAO.md](AVALIACAO.md).

## Começo rápido (Windows)

1. Instale o Python 3.13 (python.org), marcando **"Add python.exe to PATH"**.
2. Dê dois cliques em **`instalar.bat`**. Leva alguns minutos, e é só uma vez.
3. Dê dois cliques em **`preparar_mapa.bat`**. Ele baixa o mapa de Teyvat do site uma vez
   (~30 min; pode usar o PC enquanto isso) e já configura o app.
4. No Chrome que o app abrir, entre na sua conta do appsample (só na primeira vez) e deixe
   ligadas só as categorias de baú e de oculus.
5. Com o Genshin aberto: **`iniciar.bat`** roda o app completo.
6. Se algo falhar: **`diagnostico.bat`** junta tudo num `.zip` para enviar.

## Regras de segurança (não negociáveis)

- A única fonte de dados é a captura de tela, como no OBS ou no compartilhamento do Discord.
- Não lê memória, não injeta DLL, não intercepta rede, não hooka DirectX e não altera arquivos do jogo.
- Não envia teclas, cliques nem nenhuma outra entrada ao jogo. Toda automação é só no navegador.
- Não desenha nada sobre o jogo (sem overlay).
- Não se anexa ao processo do jogo: só consulta o título e a posição da janela.
- As capturas não saem do seu PC.
- O atalho de pausa usa `RegisterHotKey` do Windows: o app só é avisado dessa combinação; não lê outras teclas.

## Como funciona

```
tela do jogo ─► minimapa ─► posição no mapa base ─► coordenada do site ─► Chrome: mapa segue você
     │                                                        │
     └─► OCR das notificações ─► "baú aberto" / "oculus" ─────┴─► marcador mais próximo
                                                                  ├─ um candidato claro: marca
                                                                  └─ dúvida: destaca no site para você clicar
```

| Fase | O quê | Estado |
|---|---|---|
| 1 | Captura da janela e recorte do minimapa | Validada no seu PC (mss). O dxcam foi corrigido, mas a correção ainda não foi testada. |
| 2 | Localização (SIFT + RANSAC + correlação + Kalman), camadas, teleporte | **Testada com o Teyvat inteiro do site e seus prints:** 5 de 5 achados, ~90 ms cada. |
| 3 | Controle do mapa no Chrome (seguir, ponto do jogador, destaque) | **Testada no appsample real:** o ponto do jogador cai no lugar certo, centralizado na área visível. |
| 4 | Mapa base com tiles do site, conversão exata de coordenadas, marcadores do site | Testada no site real e numa réplica. A marcação pela interface só foi testada na réplica. |
| 5 | Detecção de coleta por OCR (RapidOCR) + regra de decisão | OCR testado em texto PT-BR e no seu print. **Faltam as regiões e os textos reais.** |
| 6 | `gmt run`, janela de status, atalho de pausa, `.bat`, diagnóstico | Feita. O executável (PyInstaller) ficou para depois (ver AVALIACAO.md). |

## Janela de status

O console do `iniciar.bat` mostra cada comando enviado ao mapa e a posição a cada 2 s. Tudo
também é gravado em `out\acoes.log`. Exemplo:

```
[14:02:10]    posição: teyvat (8123, 5610) confiança 0.82 [local] | site (-120.50, 88.10)
[14:02:11] -> mapa: centralizar em (-120.50, 88.10)
[14:02:15]    coleta detectada: baú <- exp de aventura | mora
[14:02:15] -> baú chest-1234 marcado no site e no progresso local (único candidato no raio)
```

Atalho para pausar e retomar: **Ctrl+Alt+P** (pode ser trocado no `config.toml`).

## Comandos

| Comando | Para quê |
|---|---|
| `gmt preparar-mapa` | Baixa o mapa base do site (zoom 14), cria o índice e configura |
| `gmt diagnostico` | Teste único que junta tudo num zip |
| `gmt run` | App completo |
| `gmt find-window` | Mostra se achou o jogo e qual captura vai usar |
| `gmt capture --seconds 20` | Salva minimapas e quadros; `--no-save` só mede CPU |
| `gmt calibrate print1.png ...` | Acha o centro do minimapa pela seta do jogador |
| `gmt crop print.png` | Recorta o minimapa de um print |
| `gmt build-index mapa.png` | Pré-calcula os pontos do mapa base (uma vez) |
| `gmt locate --map mapa.png prints...` | Localiza prints no mapa base |
| `gmt track --map mapa.png` | Rastreio ao vivo, sem navegador |
| `gmt site-probe` | Relatório técnico do site (biblioteca, tiles, dados, termos) |
| `gmt tiles ... --yes` | Monta o mapa base com os tiles do site (só se os termos permitirem) |
| `gmt import-markers dados.json --mapping campos.json` | Importa marcadores |
| `gmt progress export arquivo.json` / `import` | Exporta ou importa o progresso |
| `gmt detect-test prints...` | OCR em prints, para calibrar as regiões de texto |

Configuração: copie `config.example.toml` para `config.toml` e ajuste.

## Fonte do mapa base

Não existe mapa de Teyvat com licença realmente aberta: todos derivam das imagens do jogo
(propriedade da HoYoverse). Avaliados:

| Fonte | Licença | Situação |
|---|---|---|
| Tiles do appsample | Sem página de termos; `robots.txt` libera tudo | **Em uso.** Baixados no seu PC, para uso pessoal; não são redistribuídos. |
| MrPowley/genshin-map-tracker | GPL-3.0 | Mesma ideia (SIFT); o mapa fica num Google Drive. Só referência. |
| Hektin/Genshin-Chests | MIT | 3.328 baús com coordenadas do jogo. Possível dado de apoio. |
| YuehaiTeam/zhiqiong | sem licença | DLL fechada (cvAutoTrack). Descartado: não dá para auditar. |
| BetterGI | GPL-3.0 | Automação de gameplay, contra as regras. Descartado. |

## Desenvolvimento

```
pip install -e ".[dev,web,ocr]"
pytest           # 94 testes; os de navegador/OCR são pulados se faltar Chromium/RapidOCR
ruff check .
mypy src
```

```
src/gmt/
  cli.py, cli_run.py   comandos
  app.py               loop principal, janela de status, conversores de coordenada
  diagnostics.py       gmt diagnostico
  hotkey.py            atalho global (RegisterHotKey)
  config.py            config.toml
  capture/             janela do jogo, dxcam/mss, laço com FPS e CPU
  vision/              regiões relativas, minimapa, seta do jogador
  localization/        índice SIFT do mapa, localizador, Kalman
  geo/calibration.py   pixel do mapa base <-> coordenada do site
  data/markers.py      SQLite de marcadores e progresso, importação de JSON
  detect/events.py     OCR por região, baú/oculus, thread separada
  detect/resolver.py   qual marcador foi coletado (marcar ou sugerir)
  web/browser.py       controle do mapa Leaflet no Chrome
  web/probe.py         relatório técnico do site
  web/tiles.py         monta mapa base com tiles (lento, com cache e limite)
tests/                 testes; synthetic.py gera mapa e minimapas falsos
```
