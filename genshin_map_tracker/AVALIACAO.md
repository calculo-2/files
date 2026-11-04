# Avaliação honesta do projeto

Data: 04/11/2026. O que está pronto, o que pode não funcionar e o que depende de você.

## Resumo

- O código das 6 fases está escrito e tem 94 testes automáticos passando (Linux, com dados sintéticos).
- **Validado no seu PC até agora:** só a captura (Fase 1), com o mss: 5 FPS e ~10% de um núcleo de CPU.
- **Os 3 maiores riscos:** (1) os termos de uso do appsample; (2) o appsample não usar o Leaflet do jeito esperado; (3) a precisão real do minimapa contra o mapa do site.
- **O seu próximo passo:** `instalar.bat` + `diagnostico.bat`, umas 5 a 10 minutos no total, e me mandar o zip.
- **Recomendação:** começar com `auto_mark = false` (só sugerir), até a detecção de coleta ser validada.

## 1. O que está pronto e como foi verificado

| Parte | Verificado como | Confiança |
|---|---|---|
| Captura da janela (mss) | No seu PC: 5 FPS, 0 quadros pretos | Alta |
| Captura com dxcam | Bug corrigido lendo o código do dxcam 0.3.0; ainda não testada no Windows | Média |
| Recorte do minimapa | Nos seus prints: o círculo bate com a borda; centro medido pela seta | Alta (1080p) |
| Localização | Mapa sintético: 90 a 98% de acerto na 1ª tentativa, erro médio 0,34 px; rastreio em ~3 ms por quadro | Média (falta o mapa real) |
| Rejeição de erro | Imagem aleatória nunca vira posição (0 de 20); saltos só são aceitos se confirmados | Alta |
| Controle do mapa no Chrome | Leaflet 1.9.4 real num site falso: seguir, ritmo humano, ponto do jogador, destaque, marcar | Alta *se* o site usar Leaflet |
| Calibração de coordenadas | Testes com transformações conhecidas, ruído e um ponto errado | Alta |
| Banco de marcadores / progresso | Testes (SQLite, exportar/importar JSON) | Alta |
| Regra "marcar ou sugerir" | Testes: candidato único marca; vizinhos parecidos ou posição incerta só sugerem | Alta |
| OCR (RapidOCR) | Leu bem a fonte do Genshin no seu print (nomes, missão, UID); texto PT-BR renderizado | Média |
| Detecção de baú/oculus | Lógica testada; **regiões e textos reais ainda não conferidos** | Baixa |
| Atalho de pausa | Leitura do atalho testada; registro no Windows não testado | Média |

## 2. O que pode não funcionar (e o plano B)

**1. Termos de uso do appsample (risco alto, decisivo).**
Não consegui ler os termos: este ambiente não acessa o site. O diagnóstico salva os termos e o `robots.txt`.
- Se proibirem automação: o app pode só **ler a página** (seguir a posição já é automação leve), ou mudamos de site.
- Se proibirem baixar tiles: o mapa base precisa vir de outro lugar, com calibração por pontos de teletransporte (`gmt.geo.calibration`; uns 5 pontos por região).

**2. O appsample pode não usar o Leaflet "global" (risco médio).**
O controle depende de achar o objeto do mapa Leaflet na página. O gancho funciona mesmo sem variável global, mas não funciona se o site usar outra biblioteca (OpenLayers, Mapbox, canvas próprio) ou se o Leaflet estiver embutido sem o `window.L`.
- Plano B: centralizar pela URL (se o site aceitar coordenadas na URL) ou arrastar o mapa com o mouse **dentro do navegador**. É menos preciso, mas continua sem tocar no jogo.
- O `site-probe` responde isso na primeira execução.

**3. Marcar como coletado no site (risco médio).**
Não sei como o appsample marca um item; pode ser uma função da página, um clique no popup ou uma chamada ao servidor da conta.
- Até descobrir, o app guarda o progresso **localmente** e **destaca** o baú no site para você clicar.
- Se for uma chamada ao servidor, prefiro não automatizar: é o ponto com mais chance de violar os termos.

**4. Precisão real da localização (risco médio).**
O mapa sintético tem menos detalhes que o real (mais difícil num sentido, mais fácil em outro).
- Áreas que podem falhar: debaixo d'água em Fontaine, cavernas, desertos uniformes, mar aberto e cidades cheias de ícones.
- Quando falha, o app mostra "POSIÇÃO PERDIDA" e não marca nada.
- O tamanho certo do mapa base (zoom) só dá para escolher com o mapa real.

**5. Camadas subterrâneas (risco médio).**
O código aceita várias camadas, mas cada uma precisa do seu mapa base. Não sei se o appsample tem essas camadas como imagens separadas.

**6. Detecção de coleta (risco alto de ajuste fino).**
- As regiões da tela e alguns nomes em PT-BR (ex.: "Gema Essencial", "Hidróculo") são estimativas.
- O baú é inferido pelo aviso "Baú ..." seguido da lista de recompensas. Recompensas sem esse aviso (missões, desafios) só geram **sugestão**, nunca marcação.
- Precisa de 3 a 5 prints reais: com o aviso do baú, com a lista de itens e pegando um oculus.

**7. Direção do jogador (não feita).**
A seta é quase equilátera; a ponta só se distingue pelo sombreado. Desfiz a tentativa para não entregar dado errado. Não é essencial para marcar baús.

**8. Risco de banimento (nunca é zero).**
- O app só lê a tela, como o OBS faz, e não toca no jogo.
- Usar o appsample, que é de terceiros e não da HoYoverse, mantém a automação longe da sua conta do jogo.
- **Não use o mapa da HoYoLAB com este app.**

**9. Executável único (adiado).**
Empacotar Playwright e OCR num `.exe` dá ~300 MB e costuma quebrar. Os `.bat` com o ambiente Python são mais simples e confiáveis por enquanto.

## 3. O que eu consigo fazer sozinho vs. o que depende de você

**Sem você (posso continuar):**
- Mais testes e otimizações (ex.: capturar só as regiões usadas, em vez da tela inteira, para gastar menos CPU).
- Adaptadores para outros tipos de mapa (OpenLayers, centralizar pela URL), para estar pronto qualquer que seja o resultado do diagnóstico.
- Preparar o `.exe` (sem testar no Windows).

**Só com algo seu:**

| Preciso de | Por quê | Seu tempo |
|---|---|---|
| Rodar `instalar.bat` + `diagnostico.bat` e mandar o zip | Testa o dxcam e a CPU real, e traz os termos e a estrutura do site | 5 a 10 min |
| Abrir um baú ou pegar um oculus durante o diagnóstico (se der) | Calibrar o OCR com texto real | junto do item acima |
| Fazer login no appsample no Chrome do gmt (se o progresso precisar de conta) | Marcar no site com a sua conta | 1 min, uma vez |
| Decidir sobre os termos de uso | A decisão é sua: eu leio e resumo | 2 min |
| Uma sessão de teste final com `iniciar.bat` | Validar tudo junto | 10 min |

**Depois que eu receber o zip:** leio os termos, escolho a fonte do mapa base, ajusto o controle do site e as regiões do OCR, gero o `config.toml` e te mando a versão para o teste final.

## 4. Opinião

- **Vale fazer em etapas.** "O mapa segue você" (Fases 1 a 3) é a parte mais robusta e já resolve o incômodo de alternar entre o jogo e o navegador.
- A marcação automática é a parte mais frágil, porque depende do OCR e do site. Recomendo começar com `auto_mark = false`: o app destaca o baú provável e você confirma com um clique.
