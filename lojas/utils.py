import re

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def parse_brl_price(text):
    """Converte 'R$ 1.234,56' → 1234.56"""
    if not text:
        return None
    cleaned = re.sub(r"[^\d,.]", "", text.strip())
    if not cleaned:
        return None
    # formato brasileiro: ponto como milhar, vírgula como decimal
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def parse_installment_count(text):
    """Extrai o número de parcelas de textos como '12x de R$ 99,90'"""
    if not text:
        return None
    match = re.search(r"(\d+)\s*[xX×]", text)
    return int(match.group(1)) if match else None
