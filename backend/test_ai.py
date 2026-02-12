"""Test the Gemini AI integration - detailed output."""
import os
os.chdir(r"d:\projects\plasmaos\backend")

# Load env
from dotenv import load_dotenv
load_dotenv(r"d:\projects\plasmaos\.env")

print(f"API Key loaded: {bool(os.getenv('GOOGLE_API_KEY'))}")

# Test parser
from app.core.parser import extract_text_from_bytes
from app.core.ai import analyze_tender_text
import json

# Read a real test PDF we downloaded earlier
with open("test_proxy.pdf", "rb") as f:
    pdf_bytes = f.read()

print(f"PDF size: {len(pdf_bytes)} bytes")

# Extract text
text = extract_text_from_bytes(pdf_bytes, "pdf")
print(f"Extracted text: {len(text)} chars")

# Analyze with AI
print("\n--- ANALYZING WITH GEMINI ---")
result = analyze_tender_text(text)

print(f"\n{'='*60}")
print(f"GEMINI ANALYSIS RESULT")
print(f"{'='*60}")
print(json.dumps(result, indent=2, ensure_ascii=False))
