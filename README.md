# PC Price Tracker 🖥️

## Como rodar localmente

```
pip install -r requirements.txt
streamlit run app.py
```

---

## Como colocar na nuvem gratuitamente (Streamlit Community Cloud)

O Streamlit tem uma hospedagem gratuita feita exatamente para apps como esse.
O app fica rodando 24h sem gastar processamento do seu PC.

### Passo 1 — Suba o código no GitHub

1. Crie uma conta em https://github.com (gratuito)
2. Crie um repositório novo (pode ser privado)
3. Suba os arquivos do projeto. No terminal da pasta do projeto:

```
git init
git add .
git commit -m "primeiro commit"
git branch -M main
git remote add origin https://github.com/SEU_USUARIO/SEU_REPOSITORIO.git
git push -u origin main
```

Se não tiver o Git instalado: https://git-scm.com/download/win

### Passo 2 — Deploy no Streamlit Cloud

1. Acesse https://share.streamlit.io e faça login com sua conta GitHub
2. Clique em **"New app"**
3. Selecione seu repositório e confirme que o arquivo principal é `app.py`
4. Clique em **Deploy**

Pronto! Em poucos minutos o app vai estar disponível numa URL pública
(tipo `https://seuapp.streamlit.app`).

### ⚠️ Sobre o banco de dados na nuvem

O banco SQLite (`tracker.db`) fica salvo no servidor do Streamlit Cloud.
Ele persiste entre execuções normais, mas pode ser resetado se o app
ficar muito tempo sem uso ou se você fizer um novo deploy.

Para uma solução mais robusta no futuro, é possível migrar para o
Supabase (PostgreSQL gratuito em https://supabase.com), mas para começar
o SQLite funciona bem.

---

## Estrutura de arquivos

```
files/
├── app.py               ← interface Streamlit
├── database.py          ← banco SQLite
├── scraper_engine.py    ← motor de checagem
├── requirements.txt
└── lojas/
    ├── __init__.py
    ├── kabum.py
    ├── pichau.py
    ├── mercadolivre.py
    ├── amazon.py
    └── utils.py
```
