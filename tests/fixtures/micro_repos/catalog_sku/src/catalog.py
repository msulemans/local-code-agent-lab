from sku import normalize_sku


def find_product(products: dict[str, str], requested_sku: str) -> str | None:
    return products.get(normalize_sku(requested_sku))
