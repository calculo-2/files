import time
import streamlit as st
import pandas as pd
import database as db
from scraper_engine import check_all_prices

st.set_page_config(page_title="PC Price Tracker", page_icon="🖥️", layout="wide")
db.init_db()

st.title("🖥️ PC Price Tracker")
st.caption("Monitore os preços das peças do seu PC — PIX, à vista e parcelado.")

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("➕ Adicionar produto")
    with st.form("add_product_form", clear_on_submit=True):
        name = st.text_input("Nome do produto", placeholder="Ex: RTX 4060 Ti")
        store = st.selectbox("Loja", ["Kabum", "Pichau", "Mercado Livre", "Amazon"])
        identifier = st.text_input(
            "URL do produto",
            placeholder="Cole a URL completa aqui",
            help="Para Mercado Livre pode colar a URL ou o ID (ex: MLB123456789)",
        )
        target_type = st.radio(
            "Alertar quando o preço atingir o alvo em:",
            ["pix", "regular", "parcelado"],
            format_func=lambda x: {"pix": "💰 PIX / à vista", "regular": "💳 Regular", "parcelado": "📅 Parcelado"}[x],
            horizontal=True,
        )
        target_price = st.number_input("Preço alvo (R$)", min_value=0.0, step=50.0)
        submitted = st.form_submit_button("Adicionar produto", use_container_width=True)

        if submitted:
            if name and identifier and target_price > 0:
                db.add_product(name, store, identifier, target_price, target_type)
                st.success(f"✅ {name} adicionado!")
            else:
                st.error("Preencha todos os campos.")

    st.divider()

    auto_interval = st.selectbox(
        "⏱️ Verificar automaticamente a cada:",
        [0, 15, 30, 60, 120],
        format_func=lambda x: "Desativado" if x == 0 else f"{x} minutos",
    )

    if st.button("🔄 Verificar preços agora", use_container_width=True, type="primary"):
        with st.spinner("Buscando preços..."):
            alerts = check_all_prices()
        if alerts:
            st.balloons()
            st.success(f"🔔 {len(alerts)} produto(s) no preço alvo!")
        else:
            st.info("Checagem concluída. Nenhum produto no alvo ainda.")
        st.rerun()

# ── Auto-refresh ───────────────────────────────────────────────────────────────
if auto_interval > 0:
    st.caption(f"🔁 Verificação automática ativa a cada {auto_interval} minutos.")
    time.sleep(auto_interval * 60)
    check_all_prices()
    st.rerun()

# ── Lista de produtos ──────────────────────────────────────────────────────────
products = db.get_products()

if not products:
    st.info("Nenhum produto cadastrado ainda. Use a barra lateral para adicionar.")
else:
    for product in products:
        history = db.get_history(product["id"])
        latest = history[-1] if history else None

        with st.container(border=True):
            header_col, del_col = st.columns([10, 1])
            with header_col:
                st.subheader(product["name"])
                target_label = {"pix": "PIX", "regular": "Regular", "parcelado": "Parcelado"}.get(
                    product.get("target_type", "pix"), "PIX"
                )
                st.caption(f"{product['store']}  ·  Alerta em: {target_label} ≤ R$ {product['target_price']:.2f}")
            with del_col:
                if st.button("🗑️", key=f"del_{product['id']}", help="Remover produto"):
                    db.delete_product(product["id"])
                    st.rerun()

            if latest:
                pix = latest.get("pix_price")
                regular = latest.get("regular_price")
                inst = latest.get("installment_price")
                count = latest.get("installment_count")

                c1, c2, c3 = st.columns(3)

                target_type = product.get("target_type", "pix")

                with c1:
                    is_target = target_type == "pix" and pix and pix <= product["target_price"]
                    label = "💰 PIX / à vista"
                    if pix:
                        if is_target:
                            st.metric(label, f"R$ {pix:,.2f}", delta="✅ No alvo!", delta_color="normal")
                        else:
                            st.metric(label, f"R$ {pix:,.2f}")
                    else:
                        st.metric(label, "—")

                with c2:
                    is_target = target_type == "regular" and regular and regular <= product["target_price"]
                    label = "💳 Regular"
                    if regular:
                        if is_target:
                            st.metric(label, f"R$ {regular:,.2f}", delta="✅ No alvo!", delta_color="normal")
                        else:
                            st.metric(label, f"R$ {regular:,.2f}")
                    else:
                        st.metric(label, "—")

                with c3:
                    is_target = target_type == "parcelado" and inst and inst and inst * (count or 1) <= product["target_price"]
                    label = "📅 Parcelado"
                    if inst and count:
                        if is_target:
                            st.metric(label, f"{count}x R$ {inst:,.2f}", delta="✅ No alvo!", delta_color="normal")
                        else:
                            st.metric(label, f"{count}x R$ {inst:,.2f}")
                    elif inst:
                        st.metric(label, f"R$ {inst:,.2f}")
                    else:
                        st.metric(label, "—")
            else:
                st.info("Sem dados ainda — clique em **Verificar preços agora**.")

            # Gráfico de histórico (preço PIX)
            if len(history) > 1:
                df = pd.DataFrame(history)
                df["checked_at"] = pd.to_datetime(df["checked_at"])
                df = df.set_index("checked_at")
                cols_to_plot = [c for c in ["pix_price", "regular_price"] if df[c].notna().any()]
                if cols_to_plot:
                    rename = {"pix_price": "PIX", "regular_price": "Regular"}
                    st.line_chart(df[cols_to_plot].rename(columns=rename))
