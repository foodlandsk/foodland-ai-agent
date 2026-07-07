from __future__ import annotations

import argparse

from app.feed import parse_google_merchant_feed, save_products


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Google Merchant XML into products JSON.")
    parser.add_argument("feed", help="Path or URL to googleMerchant XML feed.")
    parser.add_argument("--output", default="data/products.json", help="Output JSON path.")
    args = parser.parse_args()

    products = parse_google_merchant_feed(args.feed)
    save_products(products, args.output)
    print(f"Imported {len(products)} products into {args.output}")


if __name__ == "__main__":
    main()
