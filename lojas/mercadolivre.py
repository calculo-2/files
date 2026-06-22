import re
import requests

ITEM_ID_PATTERN = re.compile(r"(MLB-?\d+)", re.IGNORECASE)


def _extract_item_id(url_or_id):
    cleaned = url_or_id.strip()
    if cleaned.upper().startswith("MLB"):
        return cleaned.upper().replace("-", "")
    match = ITEM_ID_PATTERN.search(cleaned)
    if match:
        return match.group(1).upper().replace("-", "")
    return None


def get_price(url_or_id):
    item_id = _extract_item_id(url_or_id)
    if not item_id:
        print(f"[Mercado Livre] ID não encontrado em: {url_or_id}")
        return None

    try:
        resp = requests.get(f"https://api.mercadolibre.com/items/{item_id}", timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"[Mercado Livre] Erro: {e}")
        return None

    regular_price = data.get("original_price") or data.get("price")
    pix_price = data.get("price")  # ML geralmente já mostra o menor preço

    # tenta pegar preço parcelado do primeiro método de pagamento
    installment_price = None
    installment_count = None
    try:
        resp2 = requests.get(
            f"https://api.mercadolibre.com/items/{item_id}/installments?marketplace=MLA",
            timeout=10,
        )
        if resp2.ok:
            inst_data = resp2.json()
            if inst_data:
                best = inst_data[0]
                installment_count = best.get("installments")
                installment_price = best.get("installment_amount")
    except Exception:
        pass

    return {
        "pix_price": pix_price,
        "regular_price": regular_price,
        "installment_price": installment_price,
        "installment_count": installment_count,
    }
