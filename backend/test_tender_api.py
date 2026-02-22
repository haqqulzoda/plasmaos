import requests

r = requests.get("http://localhost:8000/api/v1/tenders/")
data = r.json()
t = data[0]
print(f"ID: {t['id']}")
print(f"Title: {t['title']}")
print(f"Has compiled_master_text key: {'compiled_master_text' in t}")
print(f"compiled_master_text value: {t.get('compiled_master_text', 'NOT IN RESPONSE')}")
