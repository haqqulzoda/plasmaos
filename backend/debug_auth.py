"""Test network response interception for downloads."""
from playwright.sync_api import sync_playwright

url = "https://etender.uzex.uz/lot/465790"
target_file = "202512235105010841.pdf"  # The filename we want

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    
    downloaded_files = []
    
    # Intercept responses to capture file content
    def handle_response(response):
        url_lower = response.url.lower()
        if 'downloadfile' in url_lower and response.status == 200:
            try:
                content_type = response.headers.get("content-type", "")
                print(f"\n=== DOWNLOAD RESPONSE ===")
                print(f"URL: {response.url[:80]}")
                print(f"Status: {response.status}")
                print(f"Content-Type: {content_type}")
                
                # Get file bytes
                body = response.body()
                print(f"Body size: {len(body)} bytes")
                downloaded_files.append({"url": response.url, "body": body})
            except Exception as e:
                print(f"Error getting body: {e}")
    
    page.on("response", handle_response)
    
    page.goto(url, timeout=30000)
    page.wait_for_timeout(5000)
    
    # Click download buttons
    btns = page.query_selector_all("a.btn-success")
    print(f"Found {len(btns)} buttons")
    
    for i, btn in enumerate(btns[:2]):  # Click first 2
        try:
            print(f"\nClicking button {i+1}...")
            btn.click()
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Click failed: {e}")
    
    print(f"\n=== CAPTURED {len(downloaded_files)} FILES ===")
    for f in downloaded_files:
        print(f"  {f['url'][:60]}... ({len(f['body'])} bytes)")
    
    browser.close()
