import re
import requests
from bs4 import BeautifulSoup
from .utils import parse_brl_price, HEADERS


def get_price(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[Amazon] Erro: {e}")
        return None

    if "captcha" in resp.text.lower():
        print("[Amazon] Bloqueado por CAPTCHA. Tente mais tarde.")
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # preço principal
    regular_price = None
    whole = soup.select_one("span.a-price-whole")
    fraction = soup.select_one("span.a-price-fraction")
    if whole:
        price_text = whole.get_text(strip=True)
        if fraction:
            price_text += fraction.get_text(strip=True)
        regular_price = parse_brl_price(price_text)

    if not regular_price:
        for sel in ["#priceblock_ourprice", "#priceblock_dealprice", ".a-price .a-offscreen"]:
            el = soup.select_one(sel)
            if el:
                val = parse_brl_price(el.get_text(strip=True))
                if val:
                    regular_price = val
                    break

    # Amazon BR raramente mostra desconto PIX explícito — usa mesmo valor
    pix_price = regular_price

    # parcelado
    installment_price = None
    installment_count = None
    inst_el = soup.select_one("#installmentCalculator_feature_div") or \
              soup.select_one("[id*='installment']")
    if inst_el:
        text = inst_el.get_text(" ", strip=True)
        match = re.search(r"(\d+)\s*[xX×]\s*R?\$?\s*([\d.,]+)", text)
        if match:
            installment_count = int(match.group(1))
            installment_price = parse_brl_price(match.group(2))

    if not regular_price:
        print(f"[Amazon] Preço não encontrado em {url}")

    return {
        "pix_price": pix_price,
        "regular_price": regular_price,
        "installment_price": installment_price,
        "installment_count": installment_count,
    }
