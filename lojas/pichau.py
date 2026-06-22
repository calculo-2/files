import re
import requests
from bs4 import BeautifulSoup
from .utils import parse_brl_price, HEADERS


def get_price(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[Pichau] Erro de conexão: {e}")
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # --- PIX / à vista ---
    pix_price = None
    for el in [
        soup.select_one("[class*='pix' i]"),
        soup.select_one("[class*='avista' i]"),
        soup.select_one("[class*='cash' i]"),
    ]:
        if el:
            val = parse_brl_price(el.get_text(strip=True))
            if val:
                pix_price = val
                break

    # fallback via texto "PIX"
    if not pix_price:
        for tag in soup.find_all(string=lambda t: t and "pix" in t.lower()):
            for node in [tag.parent, tag.parent.parent if tag.parent else None]:
                if node:
                    val = parse_brl_price(node.get_text(" ", strip=True))
                    if val and val > 10:
                        pix_price = val
                        break
            if pix_price:
                break

    # --- Regular ---
    regular_price = None
    for el in [
        soup.select_one("[class*='Price_price']"),
        soup.select_one("[class*='price-value']"),
        soup.select_one("[class*='regularPrice' i]"),
        soup.select_one("span.value"),
    ]:
        if el:
            val = parse_brl_price(el.get_text(strip=True))
            if val:
                regular_price = val
                break

    if pix_price and not regular_price:
        regular_price = pix_price
    if regular_price and not pix_price:
        pix_price = regular_price

    # --- Parcelado ---
    installment_price = None
    installment_count = None
    for el in [
        soup.select_one("[class*='installment' i]"),
        soup.select_one("[class*='parcela' i]"),
    ]:
        if el:
            text = el.get_text(" ", strip=True)
            match = re.search(r"(\d+)\s*[xX×]\s*(?:de\s*)?R?\$?\s*([\d.,]+)", text)
            if match:
                installment_count = int(match.group(1))
                installment_price = parse_brl_price(match.group(2))
            break

    if not regular_price and not pix_price:
        print(f"[Pichau] Nenhum preço encontrado em {url}")

    return {
        "pix_price": pix_price,
        "regular_price": regular_price,
        "installment_price": installment_price,
        "installment_count": installment_count,
    }
