import re
import requests
from bs4 import BeautifulSoup
from .utils import parse_brl_price, HEADERS


def get_price(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[Kabum] Erro de conexão: {e}")
        return None

    if len(resp.text) < 1000:
        print("[Kabum] Resposta muito curta — possível bloqueio.")
        return None

    soup = BeautifulSoup(resp.text, "lxml")

    # --- Preço PIX / à vista ---
    # <h4 class="text-4xl text-secondary-500 font-bold ...">R$ 1.199,99</h4>
    pix_price = None
    pix_el = (
        soup.find("h4", class_=lambda c: c and "text-secondary-500" in c)
        or soup.find("h4", class_=lambda c: c and "text-4xl" in c)
    )
    if pix_el:
        pix_price = parse_brl_price(pix_el.get_text(strip=True))

    # --- Preço regular (riscado acima do PIX) ---
    regular_price = None
    regular_el = (
        soup.find(class_=lambda c: c and "line-through" in c)
        or soup.select_one("[class*='oldPrice']")
    )
    if regular_el:
        regular_price = parse_brl_price(regular_el.get_text(strip=True))
    if not regular_price:
        regular_price = pix_price

    # --- Preço parcelado ---
    # Total parcelado: <b class="text-xs font-bold text-black-700">R$ 1.411,75</b>
    # Número de parcelas: texto próximo com padrão "12x de R$..."
    installment_price = None
    installment_count = None

    inst_total_el = soup.find("b", class_=lambda c: c and "text-black-700" in c)
    if inst_total_el:
        installment_price = parse_brl_price(inst_total_el.get_text(strip=True))

        # busca o número de parcelas no elemento pai ou avô
        for ancestor in [inst_total_el.parent, inst_total_el.parent.parent if inst_total_el.parent else None]:
            if ancestor:
                text = ancestor.get_text(" ", strip=True)
                match = re.search(r"(\d+)\s*[xX×]", text)
                if match:
                    installment_count = int(match.group(1))
                    break

    # fallback: procura texto com "Nx de R$" em qualquer lugar
    if not installment_count:
        for tag in soup.find_all(string=lambda t: bool(t and re.search(r"\d+x\s*(de\s*)?R\$", t, re.IGNORECASE))):
            match = re.search(r"(\d+)\s*[xX×]", str(tag))
            if match:
                installment_count = int(match.group(1))
                break

    if not pix_price:
        print(f"[Kabum] Nenhum preço encontrado em {url}")

    print(f"[Kabum] PIX: R${pix_price} | Regular: R${regular_price} | "
          f"Parcelado: {installment_count}x (total R${installment_price})")

    return {
        "pix_price": pix_price,
        "regular_price": regular_price,
        "installment_price": installment_price,
        "installment_count": installment_count,
    }