#!/usr/bin/env python3
"""Authenticated shell route and live provider continuity on the release build.
Only loopback deterministic HTTP fixtures; no source or production services.
"""
import importlib.util, json, os, signal, subprocess, threading, time
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[2]
FRONT=Path(os.environ.get('PLASMA_FRONTEND_TEST_ROOT','/tmp/plasma-s101-release'))
OUT=ROOT/'docs/audits/s10_1/runtime'
BASE='http://localhost:3114'
def load(name,file):
 spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
 OUT.mkdir(parents=True,exist_ok=True);fixture=load('s101_runtime_fixture','s8-3-arabic-rtl-browser-acceptance.py');admin_fixture=load('s101_admin_fixture','admin-browser-acceptance.py');s72=fixture.s72
 s72.State.active=False;s72.State.users['s72-token-a'].update(ui_locale='en',default_analysis_language='uz');s72.State.users['s72-token-admin']={'id':'user-admin','ui_locale':'ar','default_analysis_language':'en','auth_version':1,'blocked':False}
 requests=[];rows=[];external=[];errors=[]
 class Handler(fixture.Handler):
  def do_GET(self):
   path=urlparse(self.path).path;requests.append(('GET',self.path))
   if path in ['/api/v1/admin/accounts','/api/v1/admin/audit-events']:return admin_fixture.Handler.do_GET(self)
   if path=='/api/v1/admin/activity':return self.send_json(200,dict(total_users=7,pending_users=1,approved_users=3,total_companies=1,pending_companies=0,approved_companies=1,analyses_count=1,reports_count=0,vault_records_count=0))
   if path=='/api/v1/admin/corpus-health':return self.send_json(200,dict(uzex_visible_count=0,world_bank_visible_count=1,adb_visible_count=0,hidden_legacy_uzex_count=0,small_uzex_count=0))
   if path=='/api/v1/admin/companies/shared-company':return self.send_json(200,{**s72.State.company,'id':'shared-company','user_id':'user-a','user_name':'Synthetic Pilot','user_email':'pilot@example.invalid'})
   if path=='/api/v1/admin/companies/shared-company/readiness':return self.send_json(200,[])
   return super().do_GET()
  def do_POST(self):requests.append(('POST',self.path));return super().do_POST()
  def do_PATCH(self):requests.append(('PATCH',self.path));return super().do_PATCH()
 server=ThreadingHTTPServer(('127.0.0.1',8114),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 env={**os.environ,'AUTH_SECRET':'s72-browser-secret','AUTH_URL':BASE,'NEXTAUTH_URL':BASE,'AUTH_TRUST_HOST':'true','NEXT_DIST_DIR':'.next-release-test','BACKEND_INTERNAL_URL':'http://127.0.0.1:8114/api/v1'}
 log=(OUT/'server.log').open('w');proc=subprocess.Popen(['npm','run','start','--','-p','3114'],cwd=FRONT,env=env,stdout=log,stderr=log,start_new_session=True)
 def check(c,m):
  if not c:raise AssertionError(m)
 def case(name,fn):
  try:e=fn();rows.append({'case':name,'status':'PASS','evidence':e})
  except Exception as e:rows.append({'case':name,'status':'FAIL','error':str(e)[:1800]})
  print(rows[-1]['status'],name,flush=True)
 def token(admin=False):
  js="import {encode} from 'next-auth/jwt'; console.log(await encode({secret:'s72-browser-secret',salt:'__Secure-authjs.session-token',token:{name:'Synthetic Pilot',email:'pilot@example.invalid',sub:'72000000-0000-4000-8000-000000000001',accessToken:process.env.S101_TOKEN,approval_status:'approved',platform_role:process.env.S101_ROLE,is_admin:process.env.S101_ROLE==='admin'},maxAge:3600}));"
  return subprocess.check_output(['node','--input-type=module','-e',js],cwd=FRONT,env={**env,'S101_TOKEN':'s72-token-admin' if admin else 's72-token-a','S101_ROLE':'admin' if admin else 'pilot_user'},text=True).strip()
 try:
  for _ in range(60):
   try:urlopen(BASE,timeout=2);break
   except Exception:time.sleep(1)
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
   def context(admin=False):
    c=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');c.add_cookies([{'name':'__Secure-authjs.session-token','value':token(admin),'domain':'localhost','path':'/','secure':True}])
    def network(r):
     if urlparse(r.request.url).hostname not in ['localhost','127.0.0.1']:external.append(r.request.url);r.abort()
     else:r.continue_()
    c.route('**/*',network);return c
   c=context();page=c.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
   routes=['','tenders?view=all','tenders/s72-tender','my-tenders','bid-preparation','bid-preparation/s73-proposal','settings','readiness-vault','tenders/s72-tender/compliance']
   for locale in ['en','uz','ru','ar']:
    s72.State.users['s72-token-a']['ui_locale']=locale
    for path in routes:
     def smoke(path=path,locale=locale):
      start=len(requests);errors.clear();r=page.goto(BASE+'/dashboard'+('/'+path if path else ''),wait_until='networkidle');expect(page.locator('h1').first).to_be_visible();check(r.status==200,'HTTP status');check('/dashboard' in page.url,'lost route');check(not errors,str(errors));check(page.locator('html').get_attribute('lang')==locale,'wrong locale');check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'overflow');check(all(method=='GET' or path.startswith('/api/v1/auth/refresh') for method,path in requests[start:]),'unexpected write');counts=Counter(urlparse(p).path for _,p in requests[start:]);check(counts['/api/v1/users/me']<=8 and counts['/api/v1/users/me/access-status']<=4,'shell budget');page.screenshot(path=str(OUT/f'{locale}-{path.replace("/","-").split("?")[0] or "dashboard"}.png'));return dict(counts)
     case(f'route/{locale}/{path or "dashboard"}',smoke)
   for locale in ['en','uz','ru','ar']:
    def onboarding(locale=locale):
     s72.State.onboarding_required=True;s72.State.users['s72-token-a']['ui_locale']=locale
     try:page.goto(BASE+'/dashboard/onboarding',wait_until='networkidle');expect(page.locator('[data-language-selector="onboarding"]')).to_be_visible();check('/onboarding' in page.url,'onboarding route');return {'locale':locale}
     finally:s72.State.onboarding_required=False
    case(f'onboarding/{locale}',onboarding)
   # Actual LanguageSelector transaction; track preserved shell DOM identity and active job.
   s72.State.active=True;s72.State.users['s72-token-a']['ui_locale']='en';page.goto(BASE+'/dashboard/settings',wait_until='networkidle');expect(page.locator('.shell-refresh-control')).to_be_visible();page.locator('[data-customer-shell]').evaluate('(e)=>e.dataset.continuity="preserved"')
   s72.State.events=[]
   for locale,native in [('uz',"O‘zbekcha"),('ru','Русский'),('ar','العربية'),('en','English')]:
    def switch(locale=locale,native=native):
     selector=page.locator('[data-language-selector="settings"]');controls=selector.get_by_role('radio');index=['en','uz','ru','ar'].index(locale);controls.nth(index).click();expect(page.locator('html')).to_have_attribute('lang',locale);check(page.url==BASE+'/dashboard/settings','route changed');expect(page.locator('[data-customer-shell]')).to_have_attribute('data-continuity','preserved');expect(page.locator('.shell-refresh-control')).to_contain_text('World Bank');check(s72.State.users['s72-token-a']['default_analysis_language']=='uz','analysis preference changed');check(s72.State.max_activity_in_flight<=1,'duplicate poller');return {'job':'s72-job','locale':locale,'auth_version':s72.State.users['s72-token-a']['auth_version'],'max_activity_in_flight':s72.State.max_activity_in_flight}
    case(f'provider/locale-switch/{locale}',switch)
   def navigation():
    page.locator('aside a[href="/dashboard/my-tenders"]').click();page.wait_for_url('**/dashboard/my-tenders');expect(page.locator('[data-customer-shell]')).to_have_attribute('data-continuity','preserved');expect(page.locator('.shell-refresh-control')).to_contain_text('World Bank');return {'shell_dom':'preserved','job':'s72-job'}
   case('provider/client-navigation',navigation)
   for locale in ['en','ar']:
    for width in [320,390,768,1440]:
     def active_responsive(locale=locale,width=width):
      s72.State.users['s72-token-a']['ui_locale']=locale;page.set_viewport_size({'width':width,'height':900});page.goto(BASE+'/dashboard/settings',wait_until='networkidle');expect(page.locator('.shell-refresh-control')).to_contain_text('World Bank');check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'active refresh shell overflow');page.screenshot(path=str(OUT/f'active-refresh-{locale}-{width}.png'));return {'width':width,'locale':locale}
     case(f'provider/active-responsive/{locale}/{width}',active_responsive)
   def touch_targets():
    touch=browser.new_context(viewport={'width':390,'height':844},has_touch=True,is_mobile=True);touch.add_cookies(c.cookies());tp=touch.new_page();tp.goto(BASE+'/dashboard/settings',wait_until='networkidle');trigger=tp.locator('.shell-mobile-trigger');box=trigger.bounding_box();check(box['width']>=44 and box['height']>=44,'small mobile navigation target');touch.close();return box
   case('shell/coarse-pointer-target',touch_targets)
   s72.State.active=False
   a=context(True);ap=a.new_page();ap.set_default_timeout(10000)
   for path in ['/admin','/admin/approvals','/admin/audit','/admin/companies/shared-company']:
    def admin_route(path=path):
     response=ap.goto(BASE+path,wait_until='networkidle');expect(ap.locator('h1').first).to_be_visible();check(response.status==200 and urlparse(ap.url).path==path,'admin route failed');expect(ap.locator('[data-admin-ltr-island]')).to_have_count(1);check(ap.locator('.app-shell').evaluate('(e)=>getComputedStyle(e).direction')=='ltr','admin direction');ap.screenshot(path=str(OUT/path.strip('/').replace('/','-'))+'.png');return {'url':path,'root_locale':ap.locator('html').get_attribute('lang'),'admin_direction':'ltr'}
    case('admin/'+path,admin_route)
   def forbidden_admin():page.goto(BASE+'/admin',wait_until='networkidle');check(urlparse(page.url).path.startswith('/dashboard'),'customer gained admin');return page.url
   case('admin/customer-denied',forbidden_admin)
   case('runtime/no-external-network',lambda:check(not external,str(external)))
   browser.close()
 finally:
  os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=15);server.shutdown();log.close();(OUT/'results.json').write_text(json.dumps(rows,indent=2))
 passed=sum(r['status']=='PASS' for r in rows);print(f'{passed}/{len(rows)} PASS')
 if passed!=len(rows):raise SystemExit(1)
if __name__=='__main__':main()
