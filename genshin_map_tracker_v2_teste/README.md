# Genshin Map Tracker (v0.2.0 — Escopo Expandido & Blindagem Anti-Ban)

Lê passivamente a imagem da tela do Genshin Impact, descobre onde você está pelo minimapa e
sincroniza com o mapa interativo [appsample](https://genshin-impact-map.appsample.com/pt/) no
Chrome do segundo monitor: o mapa segue você em tempo real e **identifica praticamente todos os
objetos interativos do mundo aberto** (baús por raridade, santuários, todos os oculi, oferendas
regionais, pontos de teleporte, estátuas, domínios, observatórios, seelies, monetoos, desafios,
baús enterrados, ~95 tipos de enigmas, caixas de mora, cristais rodopiantes, receitas e, se
quiser, todas as 64+ especialidades locais, minérios e pontos de pesca).

**Estado:** 125+ testes automatizados cobrindo localização, catálogo completo de objetos
interativos (PT-BR e Inglês), resolução em cascata, integração web e auditoria anti-ban.
Detalhes em [AVALIACAO.md](AVALIACAO.md).

## Por que NÃO usa injetor/extrator (Arquitetura Anti-Ban)

Injetores de DLL, extratores de memória (`OpenProcess` / `ReadProcessMemory`) e interceptadores
de pacotes de rede acionam o anti-cheat de kernel do jogo (`HoYoProtect`) e **causam banimento**.
Por isso este projeto mantém e audita automaticamente (`gmt seguranca`) as regras abaixo:

- **Única fonte de dados:** captura de imagem da área de trabalho (`dxcam` / `mss`), exatamente
  como o OBS Studio ou o compartilhamento de tela do Discord.
- **Zero injeção / zero memória / zero rede:** nunca abre handle no processo do jogo, nunca lê
  memória, nunca injeta DLL, nunca hooka DirectX e nunca intercepta tráfego de rede.
- **Zero input / zero overlay no jogo:** nunca envia teclas ou cliques ao Genshin Impact e nunca
  desenha janela `topmost` sobre o jogo. Toda automação ocorre exclusivamente na janela separada
  do Chrome no site externo.
- **Auditoria automática na partida:** `gmt run` e `verificar_seguranca.bat` inspecionam a árvore
  de código (AST) e os módulos em execução antes de iniciar, bloqueando qualquer API proibida.

## Objetos interativos identificados (Catálogo v0.2.0)

| Família | O que identifica e marca/sugere no mapa | Modo padrão |
|---|---|---|
| **Baús e Raridades** | Baú Comum, Sofisticado, Precioso, Luxuoso, Baú Estranho (pelo aviso ou `Diagrama:`) com desempate automático por raridade | Ligado |
| **Santuários** | Santuário das Profundezas (todas as nações de Mondstadt a Snezhnaya) | Ligado |
| **Oculi (8 regiões)** | Anemoculus, Geoculus, Electroculus, Dendroculus, Hydroculus, Pyroculus, Cryoculus, Lunoculus | Ligado |
| **Oferendas Regionais** | Calcedônia Carmesim, Espato Lúmen, Lanterna Lúmen, Carpa Espiritual, Pluma da Luz Purificadora, Selo Sagrado, Padrão de Chave I–V, Pérola da Lua Antiga, Kuuhenki, Orvalho Kuuvahki, Cristal Kresnik, Gotas de Asas Sombrias, Conjuntos Mnemônicos | Ligado |
| **Navegação & Mapa** | Ponto de Teleporte, Estação de Alta Velocidade, Ancoragem do Quebra-mar, Estátua dos Sete, Domínio, Observatório | Ligado |
| **Guias, Desafios e Enigmas** | Seelie Guia, Seelie Electro, Monetoo, Desafios Contra o Tempo, Desafio do Guerreiro/Totem, Baú Enterrado (`Escavar`) e fallback inteligente para as ~95 categorias de **Baú de Enigma** do appsample | Ligado |
| **Caixas de Mora & Selos** | Baús de Mora (Madeira, Pilha de Pedras, Pedra Destruída, Fontaine, Natlan, Nod-Krai, Lua Gelada, Snezhnaya), Selo Geo, Tesouros Ocultos | Ligado |
| **Coleção Permanente** | Cristal Rodopiante Radiante, Receitas, Livros/Tabuletas/Inscrições, Lendas Locais, Hilichurl Estranho, Aranara | Ligado |
| **Farm / Respawnáveis** | Todas as 64+ Especialidades Locais, 9 Minérios e Pontos de Pesca | Opcional (`iniciar_farm.bat` ou `include_respawnables = true`) |

> **Dica importante sobre a barra lateral do appsample:** você **não precisa** deixar dezenas de
> categorias ligadas poluindo o mapa! O `gmt` lê a tabela interna da página do appsample mesmo
> para categorias ocultas na barra lateral e, quando o ícone não está visível no canvas, abre o
> cartão direto pelo identificador do marcador (`?id=...`) para marcar na sua conta.

## Começo rápido (Windows)

1. Instale o Python 3.11+ (python.org), marcando **"Add python.exe to PATH"**.
2. Dê dois cliques em **`instalar.bat`** (só na primeira vez).
3. Dê dois cliques em **`preparar_mapa.bat`** (baixa o mapa base do site uma vez e configura).
4. No Chrome que o app abrir, entre na sua conta do [appsample](https://genshin-impact-map.appsample.com/pt/) (uma vez).
5. Com o Genshin aberto:
   - **`iniciar.bat`** para exploração 100% (todos os objetos permanentes);
   - **`iniciar_farm.bat`** se quiser rastrear também Especialidades Locais, Minérios e Pesca;
   - **`verificar_seguranca.bat`** para rodar a auditoria anti-ban e ver o catálogo completo.

## Como funciona (4 regiões de HUD + Resolução em Cascata)

```
tela do jogo ─► minimapa ─► SIFT + Correlação de Contornos + Kalman ─► Chrome: mapa segue você
     │                                                                       │
     ├─► Região Prompt / Pickup (direita)  ─┐                                │
     ├─► Região Obtido (esquerda)          ─┼─► Detector + Memória ──────────┴─► Resolução em Cascata:
     └─► Região Banner Central (topo)      ─┘    Contextual (Escavar,            1. Contexto (Desafio/Escavar/Seelie)
                                                 Desafio, Raridade)              2. Subtipo exato (ex.: Baú Precioso)
                                                                                 3. Categoria principal (Baú/Teleporte/...)
                                                                                 4. Fallback automático p/ Baú de Enigma
```

## Comandos principais

| Comando | Para quê |
|---|---|
| `gmt run` | Roda o rastreador completo (adicione `--respawnables` para farm de especialidades/minérios) |
| `gmt preparar-mapa` | Baixa o mapa base do site (zoom 14), cria o índice SIFT e atualiza o `config.toml` |
| `gmt categorias` | Lista todas as 120+ categorias suportadas (`--all`) ou testa textos (`--testar "Espato Lúmen x1"`) |
| `gmt seguranca` | Executa a auditoria estática (AST) e de runtime confirmando zero risco de injeção/memória |
| `gmt diagnostico` | Teste único que valida segurança, captura, OCR multi-objeto e site num `.zip` |
| `gmt detect-test prints...` | Roda OCR nas 4 regiões da tela e mostra quais objetos interativos foram reconhecidos |
| `gmt progress stats` | Exibe contagem e porcentagem local por categoria (`export` / `import` para JSON) |

Atalho global para pausar e retomar (`RegisterHotKey`): **Ctrl+Alt+P**.
