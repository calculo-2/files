from lojas import SCRAPERS
import database as db


def check_all_prices():
    alerts = []
    products = db.get_products()

    for product in products:
        scraper = SCRAPERS.get(product["store"])
        if not scraper:
            print(f"Loja desconhecida: {product['store']}")
            continue

        result = scraper.get_price(product["identifier"])
        if not result:
            continue

        pix = result.get("pix_price")
        regular = result.get("regular_price")
        installment = result.get("installment_price")
        count = result.get("installment_count")

        db.save_price(product["id"], pix, regular, installment, count)

        # verifica alerta com base no tipo de preço escolhido
        target_type = product.get("target_type", "pix")
        if target_type == "pix":
            compare_price = pix
        elif target_type == "parcelado":
            compare_price = installment
        else:
            compare_price = regular

        if compare_price and compare_price <= product["target_price"]:
            alerts.append({
                **product,
                "pix_price": pix,
                "regular_price": regular,
                "installment_price": installment,
                "installment_count": count,
            })

    return alerts


if __name__ == "__main__":
    db.init_db()
    found = check_all_prices()
    if found:
        print("\n🔔 Produtos no preço alvo:")
        for item in found:
            print(f" - {item['name']} | PIX: R$ {item['pix_price']} | "
                  f"Regular: R$ {item['regular_price']} | "
                  f"Alvo: R$ {item['target_price']}")
    else:
        print("Nenhum produto atingiu o preço alvo.")
