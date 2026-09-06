#!/usr/bin/env python3
"""S9.1 synthetic browser audit. Runs only a loopback frontend and existing mock API;
S91_FRONTEND_ROOT may point to a clean copy of the tracked frontend. Requires
Node on PATH and Playwright Chromium. Never use a production app URL.
"""
import importlib.util,json,os,subprocess,threading,time
from collections import Counter
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from playwright.sync_api import sync_playwright


def main():
    root=Path(__file__).resolve().parents[2];front=Path(os.environ.get('S91_FRONTEND_ROOT',str(root/'frontend')));out=root/'docs/audits/s9_1_browser';out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('s83',root/'frontend/tests/s8-3-arabic-rtl-browser-acceptance.py');s83=importlib.util.module_from_spec(spec);spec.loader.exec_module(s83);s72=s83.s72
    s72.State.users['s72-token-a'].update(ui_locale='en',default_analysis_language='en');s72.State.active=False
    audit_requests=[]
    class AuditHandler(s83.Handler):
     def do_GET(self):
      audit_requests.append(('GET',self.path));super().do_GET()
     def do_POST(self):
      audit_requests.append(('POST',self.path));super().do_POST()
     def do_PATCH(self):
      audit_requests.append(('PATCH',self.path));super().do_PATCH()
    server=ThreadingHTTPServer(('127.0.0.1',8114),AuditHandler);threading.Thread(target=server.serve_forever,daemon=True).start()
    env=os.environ.copy();env.update(AUTH_SECRET='s72-browser-secret',NEXTAUTH_URL='http://localhost:3114',AUTH_URL='http://localhost:3114',AUTH_TRUST_HOST='true',BACKEND_INTERNAL_URL='http://127.0.0.1:8114/api/v1',NEXT_DIST_DIR='.next-s91-browser',PATH=env['PATH'])
    log=open('/tmp/plasma-s91-browser-server.log','w');proc=subprocess.Popen(['npm','run','dev','--','-p','3114'],cwd=front,env=env,stdout=log,stderr=log,start_new_session=True)
    rows=[]
    try:
     for _ in range(90):
      try:
       urlopen('http://localhost:3114',timeout=2);break
      except Exception:time.sleep(1)
     token=subprocess.check_output(['node','tests/make-s72-session.mjs'],cwd=front,env=env,text=True).strip()
     with sync_playwright() as pw:
      browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
      context=browser.new_context(viewport={'width':390,'height':844});context.add_cookies([{'name':'authjs.session-token','value':token,'url':'http://localhost:3114'}])
      page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
      surfaces=[('explorer','tenders?view=all'),('details','tenders/s72-tender'),('my-tenders','my-tenders'),('bid-preparation','bid-preparation'),('compliance','tenders/s72-tender/compliance'),('readiness','readiness-vault'),('settings','settings')]
      for locale in ['en','uz','ru','ar']:
       s72.State.users['s72-token-a']['ui_locale']=locale
       for label,path in surfaces:
        before=len(audit_requests);before_writes=len(s72.State.domain_writes);errors.clear()
        response=page.goto('http://localhost:3114/dashboard/'+path,wait_until='networkidle',timeout=90000)
        page.wait_for_timeout(400)
        file=f'{locale}-{label}.png';page.screenshot(path=str(out/file),full_page=True)
        snapshot=page.evaluate('''() => ({lang:document.documentElement.lang,dir:document.documentElement.dir,width:innerWidth,scroll:document.documentElement.scrollWidth,headings:[...document.querySelectorAll('h1,h2')].map(x=>x.textContent),unlabelled:[...document.querySelectorAll('input,select,textarea')].filter(x=>!x.labels?.length&&!x.getAttribute('aria-label')&&!x.getAttribute('aria-labelledby')&&x.type!=='hidden').length})''')
        reqs=audit_requests[before:];counts=Counter(str(x) for x in reqs)
        row={'locale':locale,'surface':label,'status':response.status,'final_path':page.url.split('3114')[-1],'screenshot':file,'dom':snapshot,'browser_errors':list(errors),'backend_requests':dict(counts),'domain_writes':s72.State.domain_writes[before_writes:]}
        rows.append(row);print(locale,label,snapshot['lang'],snapshot['dir'],snapshot['scroll'],len(reqs),flush=True)
      browser.close()
    finally:
     import signal
     try: os.killpg(proc.pid,signal.SIGTERM)
     except ProcessLookupError: pass
     server.shutdown();server.server_close();log.close()
     (out/'results.json').write_text(json.dumps({'method':'unchanged tracked frontend in isolated Linux checkout; existing S8.3 HTTP fixtures; real Chromium; 390x844; route loads only; no production/backend/provider traffic','rows':rows},indent=2,ensure_ascii=False))


if __name__ == "__main__":
    main()
