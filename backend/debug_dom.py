"""Debug script - check lot section finding."""
from playwright.sync_api import sync_playwright
import re

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    page.goto("https://etender.uzex.uz/lots/2/0", timeout=30000)
    page.wait_for_load_state("networkidle", timeout=15000)
    
    # Get card content
    card = page.query_selector("div.card")
    full_text = card.inner_text() if card else ""
    lines = [l.strip() for l in full_text.split('\n') if l.strip()]
    
    print(f"Total lines: {len(lines)}")
    
    # Get lot links
    links = page.query_selector_all("a[href*='/lot/']")
    print(f"Total lot links: {len(links)}")
    
    # Check first few unique lot IDs
    seen = set()
    for link in links[:5]:
        href = link.get_attribute("href") or ""
        lot_match = re.search(r'/lot/(\d+)', href)
        if not lot_match:
            continue
        lot_id = lot_match.group(1)
        if lot_id in seen:
            continue
        seen.add(lot_id)
        
        print(f"\nLot ID: {lot_id}")
        
        # Find matching line
        for i, line in enumerate(lines):
            if lot_id in line:
                print(f"  Found in line {i}: '{line[:60]}'")
                # Show next few lines
                for j in range(i, min(i+5, len(lines))):
                    print(f"  {j}: {lines[j][:70]}")
                break
        else:
            print("  NOT FOUND in any line!")
    
    browser.close()
