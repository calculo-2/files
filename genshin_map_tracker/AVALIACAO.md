# Avaliação honesta do projeto

Atualizada em 07/11/2026, depois do diagnóstico do seu PC e de testes no site real.

## Resumo

- **Mapa seguindo você:** testado no appsample real. O site usa Leaflet 1.9.4, o app encontra o mapa e o move.
- **Localização:** testada com tiles reais do site e os seus prints. Ela acha você e bate a mesma posição entre zooms diferentes.
- **Marcação de baú/oculus no site:** implementada pela interface (abre o marcador e clica no botão verde). Só foi testada numa réplica; no site real **precisa do seu PC e de login** no appsample.
- **Seu próximo passo:** `instalar.bat` → `preparar_mapa.bat` (~30 min, uma vez) → `iniciar.bat`.

## 0. Primeira sessão real (07/11, ~10 min no seu PC)

- **Localização:** funcionou bem (confiança de 0,7 a 0,9), e o mapa do site seguiu você.
- **Coleta:** nenhuma foi detectada. As regiões e os textos do OCR ainda não batem com o jogo.
- **CPU:** 309% de um núcleo, alto demais. Causas: OCR sem limite e busca global a cada quadro com a posição perdida.
- **Perdas de posição:** frequentes, às vezes por minutos.

Correções feitas:
- OCR com 2 threads e no máximo 1 leitura por segundo (medido: 116 ms por região).
- Busca global no máximo 2 vezes por segundo.
- Busca ampla em volta da última posição antes da busca global.
- Registro automático do texto lido (`out/ocr`) e dos momentos de perda (`out/perdido`), tudo empacotado num zip ao encerrar.

## 1. O que foi verificado e como

| Parte | Como foi verificado | Confiança |
|---|---|---|
| Captura (mss) | No seu PC: 5 FPS, ~10% de um núcleo | Alta |
| Captura (dxcam) | Corrigida pelo código do dxcam; seu diagnóstico rodou com o jogo minimizado | Média |
| Recorte do minimapa | Seus prints (centro medido pela seta) | Alta (1080p) |
| Mapa base do site | Tiles reais baixados, montados e conferidos visualmente | Alta |
| Localização | Teyvat inteiro (zoom 14, 689 mil pontos): 5 de 5 prints achados, ~90 ms cada, posição igual à esperada em menos de 1 px | Alta na área testada |
| Posição no site | Ponto do jogador desenhado no appsample real cai no mesmo lugar do seu minimapa | Alta |
| Seguir no site | No appsample real: mapa encontrado e movido para a posição pedida | Alta |
| Tabela de marcadores do site | Lida no site real (id, tipo, posição, "found") | Alta |
| Marcar pela interface | Réplica local com a mesma estrutura: marca, detecta "já marcado" e pedido de login | Média (falta o site real) |
| Detecção de coleta (OCR) | Lê bem a fonte do jogo no seu print; a lógica foi testada | Baixa a média (faltam prints de baú e oculus) |

## 2. O que descobri no site

- **Termos de uso:** não há página de termos. O `robots.txt` é `Allow: /` (permite tudo).
- **Formato do mapa:** tiles de 256 px em `game-cdn.appsample.com`, com o y crescendo para cima. O site também publica a lista dos tiles vazios.
- **Atualizações do mapa:** a configuração vem na própria página, e o app a lê sozinho. Quando o jogo atualizar o mapa, basta rodar o `preparar_mapa.bat` de novo.
- **Onde fica o "encontrado":** **na sua conta do appsample** (nuvem). Sem login, o site pede para entrar. Por isso o app marca clicando no botão do site, como você faria.
- **Navegador sem janela:** o site trata navegadores "headless" como robôs e não carrega os dados completos. No seu PC o app usa o seu Chrome normal, com janela. Não tentei contornar essa checagem.
- **Camadas subterrâneas** (Despenhadeiro, Enkanomiya etc.): são páginas separadas. O `preparar-mapa --mapa chasm` já sabe montá-las, mas não foram testadas.

## 3. O que ainda pode não funcionar

1. **Marcação no site real (risco médio).** Pode falhar se o popup ou o botão do site forem diferentes do que vi no código. Nesse caso o app avisa "não deu para marcar" e você marca à mão.
2. **Detecção de coleta (risco alto de ajuste fino).** As áreas da tela onde aparecem as notificações ainda são estimadas. Recomendo começar com `auto_mark = false`: o app só destaca o baú provável e você confirma.
3. **Memória (risco baixo a médio).** Medido: ~1,6 GB de RAM no pico com o Teyvat inteiro no zoom 14 (o arquivo do índice tem 105 MB). Com 16 GB de RAM, junto com o jogo, deve ir bem. Se pesar, dá para usar `--zoom 13`, com menos acerto.
4. **Lugares difíceis.** Debaixo d'água, cavernas e mar aberto podem perder a posição. Nesses casos o app avisa e não marca nada.
5. **Direção do personagem:** não foi feita (a seta é quase simétrica).
6. **Risco à conta do jogo:** nunca é zero, mas o app só lê a tela; toda a automação fica no navegador, num site de terceiros.

## 4. O que depende de você

| Preciso de | Para | Tempo |
|---|---|---|
| Rodar `instalar.bat` e `preparar_mapa.bat` | Baixar o mapa no seu PC | ~35 min (pode usar o PC enquanto isso) |
| Fazer login no appsample no Chrome do app | Marcar com a sua conta | 1 min, uma vez |
| Um teste com `iniciar.bat`, abrindo 1 ou 2 baús | Validar a marcação e o OCR | 10 min |
| Se falhar: `diagnostico.bat` e me mandar o zip | Eu ajusto | 3 min |
