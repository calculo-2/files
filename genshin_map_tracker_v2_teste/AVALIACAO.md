# Avaliação técnica e evolução do projeto (v0.2.1)

## 0. O que mudou da v0.2.0 para a v0.2.1 (revisão)

- **Replay das 6 sessões reais**: o texto do OCR de todas as sessões (3.345 leituras) foi
  reproduzido na v0.2.0. Ela criava eventos falsos de "Caixa de Mora" (Mora x10000-x20000 de
  recompensa de missão/mecânica regional, e "Selo Cryo", que vem dentro dos baús de Snezhnaya)
  e de "Receita" (receita que veio dentro de um baú). Corrigido: Caixa de Mora só depois de
  "Escavar" e só como sugestão; "Selo X" passa a contar como item de baú; receita/livro dentro
  da lista de um baú é ignorado. Agora o replay dá os mesmos eventos da versão estável.
- **Categorias não validadas não marcam sozinhas** (padrão): destacam no mapa e vão para
  `incertos.log`. Opção `auto_marcar_em_teste` para liberar.
- **Baú resolvido só como "Baú de Enigma"** passa pela confirmação de 30 s (como os incertos).
- **CPU**: o aviso central do topo é lido no máximo a cada 2 s.
- **Qualidade**: zero avisos de lint/tipos; arquivos `.bat` com quebra de linha do Windows.



## 1. O que foi expandido na v0.2.0

1. **Cobertura quase total de objetos interativos (`src/gmt/data/catalog.py` — 120+ tipos):**
   - Antes o projeto só reconhecia `chest` genérico e 8 `oculi`, perdendo ~55% dos baús do
     [appsample](https://genshin-impact-map.appsample.com/pt/) (que o site cadastra apenas na
     seção **Baú de Enigma**, como Seelies, Monetoos, Desafios Contra o Tempo, Monumentos
     Elementais, Quebra-Cabeças de Tocha, Baús Enterrados e Mini Quebra-Cabeças), além de ignorar
     Teleportes, Estátuas, Domínios, Observatórios, Oferendas Regionais e Caixas de Mora.
   - Agora o catálogo cobre **40+ categorias permanentes de exploração** (incluindo raridade
     individual de baús, `Diagrama:` de Baú Estranho, todas as 13 oferendas regionais até Lua
     Gelada/Snezhnaya, Teleportes/Estátuas/Domínios/Observatórios, todas as ~95 subcategorias de
     Baú de Enigma do appsample em PT-BR e EN, Caixas de Mora/Selos Elementais, Cristais
     Rodopiantes e Receitas) + **75+ categorias respawnáveis opcionais** (62+ Especialidades
     Locais, 9 Minérios e Pesca).

2. **Quarta região de HUD (`BANNER_REGION` central) e Memória Contextual (`events.py`):**
   - Adicionada âncora central (`anchor="center"`, compatível com 16:9 e ultrawide 21:9) para ler
     banners de topo (`"Ponto de Teleporte desbloqueado"`, `"Domínio desbloqueado"`,
     `"Desafio Concluído"`, `"Novo Observatório"`, `"Lenda Local"`), pulando quadros vazios sem
     custo extra de CPU.
   - Memória contextual liga ações prévias (`"Escavar"`, `"Desafio Contra o Tempo"`, `"Seelie"`,
     `"Monetoo"`, `"Investigar"`) e a raridade exata lida no aviso (`"Baú Precioso"`,
     `"Baú Estranho"`) ao evento de recompensa subsequente.

3. **Resolução em Cascata + Marcação de Categorias Ocultas (`resolver.py`, `app.py`, `browser.py`):**
   - Desempata automaticamente dois baús próximos quando o aviso informou a raridade exata.
   - Quando um baú é aberto num ponto onde o appsample cadastrou apenas o enigma (ex.: `Seelie Guia`
     ou `Mini Quebra-Cabeças`), faz fallback automático para `puzzle_chest`, com trava temporal de
     15 s para nunca marcar duas vezes após `"Desafio Concluído"`.
   - Se a categoria estiver desligada na barra lateral do appsample (para manter o mapa limpo),
     `MapBrowser` abre o marcador direto pelo link `?id=...` sem travar nem acusar falso overlap.

4. **Blindagem Anti-Ban Auditável (`src/gmt/safety.py`):**
   - Nenhum injetor, extrator de memória ou interceptador de rede foi nem deve ser usado: no
     Genshin Impact, `OpenProcess`/`ReadProcessMemory`/DLL/WinDivert geram banimento pelo
     `HoYoProtect`. O módulo `gmt.safety` audita automaticamente todo o código antes de rodar.

## 2. Limitações naturais da leitura puramente visual (honestidade técnica)

- **Enigmas silenciosos sem baú:** raros mecanismos intermediários que não exibem banner nem
  entregam baú/item ao terminar só são marcados quando geram o baú ou notificação final.
- **Login uma vez no Chrome do app:** a marcação na nuvem do appsample exige estar logado no
  perfil `.chrome-gmt` que o app abre no navegador.
