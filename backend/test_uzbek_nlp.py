import json
from urllib.request import urlopen

schema = json.loads(urlopen("http://localhost:8000/openapi.json").read())

# Find all paths containing "analyze"
for path, methods in schema["paths"].items():
    if "analyze" in path.lower():
        print(f"FOUND: {path}")
        for method, details in methods.items():
            print(f"  {method.upper()}: {details.get('summary', 'no summary')}")

# Also check response schema
schemas = schema.get("components", {}).get("schemas", {})
for name in sorted(schemas.keys()):
    if "analyze" in name.lower() or "compliance" in name.lower():
        props = schemas[name].get("properties", {})
        print(f"\nSchema '{name}': {list(props.keys())}")
