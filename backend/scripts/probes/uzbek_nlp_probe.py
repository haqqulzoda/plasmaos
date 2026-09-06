"""Explicit OpenAPI analysis/Compliance schema inspection; no network at import."""


def main(argv=None):
    import argparse
    import json
    from urllib.request import urlopen

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args(argv)
    if not 0 < args.timeout <= 120:
        parser.error("--timeout must be greater than zero and at most 120 seconds")
    with urlopen(args.base_url.rstrip("/") + "/openapi.json", timeout=args.timeout) as response:
        schema = json.load(response)
    for path, methods in schema["paths"].items():
        if "analyze" in path.lower():
            print(f"FOUND: {path}")
            for method, details in methods.items():
                if isinstance(details, dict):
                    print(f"  {method.upper()}: {details.get('summary', 'no summary')}")
    for name, details in sorted(schema.get("components", {}).get("schemas", {}).items()):
        if "analyze" in name.lower() or "compliance" in name.lower():
            print(f"Schema '{name}': {list(details.get('properties', {}))}")


if __name__ == "__main__":
    main()
