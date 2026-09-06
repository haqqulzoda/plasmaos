"""Explicit live Tender API inspection; not a product regression test."""


def main(argv=None):
    import argparse
    import requests

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 120:
        parser.error("--timeout must be greater than zero and at most 120 seconds")
    response = requests.get(args.base_url.rstrip("/") + "/api/v1/tenders/", timeout=args.timeout)
    response.raise_for_status()
    data = response.json()
    if not data:
        print("No tenders returned.")
        return
    tender = data[0]
    print(f"ID: {tender['id']}")
    print(f"Title: {tender['title']}")
    print(f"Has compiled_master_text key: {'compiled_master_text' in tender}")
    print(f"compiled_master_text value: {tender.get('compiled_master_text', 'NOT IN RESPONSE')}")


if __name__ == "__main__":
    main()
