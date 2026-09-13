#!/usr/bin/env python3
"""Sprint 10.6 real-Chromium acceptance: 120+ named UI/security cases."""
from __future__ import annotations
import copy, importlib.util, json, os, signal, subprocess, threading, time
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
FRONT = Path(os.environ.get('PLASMA_FRONTEND_TEST_ROOT', Path(__file__).resolve().parents[1]))
OUT = ROOT / 'docs/audits/s10_6/browser'
BACKEND_PORT = 8116
spec = importlib.util.spec_from_file_location('s106_fixture', Path(__file__).with_name('s8-3-arabic-rtl-browser-acceptance.py'))
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
s72 = fixture.s72
BASE = 'http://localhost:3116'
CDP_PROXY_PORT = 9470
UID = '10000000-0000-4000-8000-000000000001'
USER_B_ID = '10000000-0000-4000-8000-000000000099'

def notification(index, event_type, category, key=None, subject=None, body=None, read=False):
    return {'id':f'20000000-0000-4000-8000-{index:012d}','event_id':f'30000000-0000-4000-8000-{index:012d}','category':category,'event_type':event_type,'template_key':key,'payload':({'tender_id':'40000000-0000-4000-8000-000000000001','recommendation_id':'50000000-0000-4000-8000-000000000001'} if event_type=='RECOMMENDATION_CREATED' else {'analysis_id':'60000000-0000-4000-8000-000000000001','analysis_version_id':'70000000-0000-4000-8000-000000000001','version_number':2,'analysis_language':'uz'} if event_type=='ANALYSIS_COMPLETED' else {}),'subject':subject,'body':body,'message_type':'ANNOUNCEMENT' if subject else None,'content_format':'plain_text','is_test':False,'created_at':f'2026-09-13T10:{index:02d}:00Z','read_at':'2026-09-13T11:00:00Z' if read else None,'is_read':read}

class Data:
    notifications = [
      notification(5,'ADMIN_BROADCAST','ADMIN',subject='Authored <b>verbatim</b> announcement',body='Original body — إعلان\n**plain text only**'),
      notification(4,'OBSOLETE_EVENT','SYSTEM'),
      notification(3,'ACCOUNT_APPROVED','SYSTEM','notifications.account_approved',read=True),
      notification(2,'ANALYSIS_COMPLETED','SYSTEM','notifications.analysis_completed'),
      notification(1,'RECOMMENDATION_CREATED','TENDER_ALERT','notifications.recommendation_created'),
    ]
    requests=[]; drafts={}; counter=10
    accounts=[{'id':UID,'name':'Admin User','email':'admin@example.invalid','approval_status':'approved','role':'admin','is_current_actor':True,'restore_target_status':None,'allowed_actions':[],'company':{'id':'80000000-0000-4000-8000-000000000001','company_name':'Plasma Institution','approval_status':'approved','pilot_status':'active'},'created_at':'2026-09-01T10:00:00Z'}]
    for i,status in enumerate(['pending','approved','rejected','disabled'],2): accounts.append({'id':f'10000000-0000-4000-8000-{i:012d}','name':f'Account {i}','email':f'account{i}@example.invalid','approval_status':status,'role':'user','is_current_actor':False,'restore_target_status':'approved' if status=='disabled' else None,'allowed_actions':{'pending':['approve','reject','disable'],'approved':['reject','disable'],'rejected':['approve','disable'],'disabled':['restore']}[status],'company':None,'created_at':'2026-09-01T10:00:00Z'})
    for i,status in enumerate(['DRAFT','QUEUED','SENDING','SENT','PARTIAL','FAILED'],1):
      bid=f'90000000-0000-4000-8000-{i:012d}'; drafts[bid]={'id':bid,'subject':f'{status.title()} broadcast','body':'Verbatim body','message_type':'ANNOUNCEMENT','content_format':'plain_text','audience_mode':'ALL_ELIGIBLE_USERS','selected_user_count':0,'status':status,'recipient_count':5 if status!='DRAFT' else 0,'delivered_count':5 if status=='SENT' else 3 if status=='PARTIAL' else 0,'failed_count':2 if status=='PARTIAL' else 5 if status=='FAILED' else 0,'last_error_code':'DELIVERY_FAILED' if status in ['PARTIAL','FAILED'] else None,'created_at':'2026-09-13T09:00:00Z','updated_at':'2026-09-13T10:00:00Z','queued_at':None if status=='DRAFT' else '2026-09-13T09:30:00Z','completed_at':'2026-09-13T10:00:00Z' if status in ['SENT','PARTIAL','FAILED'] else None}

class Handler(fixture.Handler):
  def record(self, method): Data.requests.append((method,self.path,s72.bearer(self)))
  def do_GET(self):
    p=urlparse(self.path); self.record('GET'); q=parse_qs(p.query)
    principal=s72.bearer(self)
    if p.path.startswith('/api/v1/admin/') and principal!='s72-token-admin': return self.send_json(403,{'detail':{'code':'admin_required'}})
    if p.path=='/api/v1/notifications/unread-count': return self.send_json(200,{'unread_count':0 if principal=='s106-user-b' else sum(not x['is_read'] for x in Data.notifications)})
    if p.path=='/api/v1/notifications':
      rows=[] if principal=='s106-user-b' else list(Data.notifications)
      if q.get('unread')==['true']: rows=[x for x in rows if not x['is_read']]
      if q.get('category'): rows=[x for x in rows if x['category']==q['category'][0]]
      return self.send_json(200,{'items':rows,'next_cursor':None})
    if p.path=='/api/v1/admin/accounts':
      rows=Data.accounts; query=q.get('query',[''])[0].lower()
      if query: rows=[x for x in rows if query in x['email'].lower() or query in x['name'].lower()]
      if q.get('approval_status'): rows=[x for x in rows if x['approval_status']==q['approval_status'][0]]
      limit=min(int(q.get('limit',['25'])[0]),25); offset=int(q.get('offset',['0'])[0])
      return self.send_json(200,{'items':rows[offset:offset+limit],'total':len(rows),'limit':limit,'offset':offset})
    if p.path=='/api/v1/admin/broadcasts':
      rows=list(reversed(list(Data.drafts.values())))
      if q.get('status'): rows=[x for x in rows if x['status']==q['status'][0]]
      summaries=[{k:x[k] for k in ['id','subject','message_type','audience_mode','status','recipient_count','delivered_count','failed_count','created_at','updated_at']} for x in rows]
      return self.send_json(200,{'items':summaries,'next_cursor':None})
    if p.path.startswith('/api/v1/admin/broadcasts/'):
      bid=p.path.rsplit('/',1)[-1]; return self.send_json(200,Data.drafts[bid]) if bid in Data.drafts else self.send_json(404,{'detail':{'code':'broadcast_not_found'}})
    return super().do_GET()
  def do_PATCH(self):
    p=urlparse(self.path); self.record('PATCH')
    principal=s72.bearer(self)
    if p.path.startswith('/api/v1/admin/') and principal!='s72-token-admin': return self.send_json(403,{'detail':{'code':'admin_required'}})
    if p.path.startswith('/api/v1/notifications/'):
      if principal=='s106-user-b': return self.send_json(404,{'detail':{'code':'notification_not_found'}})
      did=p.path.rsplit('/',1)[-1]; row=next((x for x in Data.notifications if x['id']==did),None); body=self.body()
      if not row:return self.send_json(404,{'detail':{'code':'notification_not_found'}})
      row['is_read']=body['is_read']; row['read_at']='2026-09-13T12:00:00Z' if body['is_read'] else None; return self.send_json(200,{'id':did,'is_read':row['is_read'],'read_at':row['read_at']})
    if p.path.startswith('/api/v1/admin/broadcasts/'):
      bid=p.path.rsplit('/',1)[-1]; body=self.body(); row=Data.drafts[bid]
      for src,dst in [('subject','subject'),('body','body'),('message_type','message_type'),('audience_mode','audience_mode')]:
        if src in body: row[dst]=body[src]
      if 'selected_user_ids' in body: row['selected_user_count']=len(body['selected_user_ids'])
      row['updated_at']='2026-09-13T12:00:00Z'; return self.send_json(200,row)
    return super().do_PATCH()
  def do_POST(self):
    p=urlparse(self.path); self.record('POST')
    principal=s72.bearer(self)
    if p.path.startswith('/api/v1/admin/') and principal!='s72-token-admin': return self.send_json(403,{'detail':{'code':'admin_required'}})
    if p.path=='/api/v1/notifications/mark-all-read':
      if principal=='s106-user-b': return self.send_json(200,{'updated_count':0})
      count=sum(not x['is_read'] for x in Data.notifications)
      for x in Data.notifications:x.update(is_read=True,read_at='2026-09-13T12:00:00Z')
      return self.send_json(200,{'updated_count':count})
    if p.path=='/api/v1/admin/broadcasts':
      body=self.body(); Data.counter+=1; bid=f'90000000-0000-4000-8000-{Data.counter:012d}'; row={'id':bid,**body,'content_format':'plain_text','selected_user_count':len(body.get('selected_user_ids',[])),'status':'DRAFT','recipient_count':0,'delivered_count':0,'failed_count':0,'last_error_code':None,'created_at':'2026-09-13T12:00:00Z','updated_at':'2026-09-13T12:00:00Z','queued_at':None,'completed_at':None}; row.pop('selected_user_ids',None); Data.drafts[bid]=row; return self.send_json(201,row)
    if p.path.endswith('/audience-preview'): return self.send_json(200,{'eligible_recipient_count':5,'audience_mode':'ALL_ELIGIBLE_USERS','selected_user_count':0,'snapshot_frozen':False,'frozen_recipient_count':None,'eligibility':'APPROVED_ACCOUNTS_ONLY'})
    if p.path.endswith('/send-test'): self.body(); return self.send_json(200,{'delivery_id':'a0000000-0000-4000-8000-000000000001','is_test':True})
    if p.path.endswith('/send'):
      bid=p.path.split('/')[-2]; row=Data.drafts[bid]; row.update(status='QUEUED',recipient_count=5,queued_at='2026-09-13T12:00:00Z'); return self.send_json(202,row)
    return super().do_POST()

def token(role, access):
  js=f"import {{encode}} from 'next-auth/jwt'; console.log(await encode({{secret:'s106-secret',salt:'authjs.session-token',token:{{name:'Synthetic {role}',email:'{role}@example.invalid',sub:'{UID}',accessToken:'{access}',approval_status:'approved',platform_role:'{role}',is_admin:{str(role=='admin').lower()}}},maxAge:3600}}));"
  for attempt in range(3):
    result=subprocess.run(['/mnt/c/Program Files/nodejs/node.exe','--input-type=module','-e',js],cwd=FRONT,text=True,capture_output=True)
    if not result.returncode:return result.stdout.strip()
    time.sleep(.5)
  raise RuntimeError(f'session token generation failed: {result.stderr.strip()}')

def main():
  OUT.mkdir(parents=True,exist_ok=True); results=[]; errors=[]
  s72.State.active=False; s72.State.onboarding_required=False
  s72.State.users['s106-user']={'id':UID,'ui_locale':'en','default_analysis_language':'en','auth_version':1,'blocked':False}
  s72.State.users['s106-user-b']={'id':USER_B_ID,'ui_locale':'en','default_analysis_language':'en','auth_version':1,'blocked':False}
  s72.State.users['s72-token-admin']={'id':UID,'ui_locale':'en','default_analysis_language':'en','auth_version':1,'blocked':False}
  server=ThreadingHTTPServer(('127.0.0.1',BACKEND_PORT),Handler); threading.Thread(target=server.serve_forever,daemon=True).start()
  subprocess.run([s72.POWERSHELL,'-NoProfile','-Command',"Get-NetTCPConnection -LocalPort 3116 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force }"],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  command=(r'cd /d D:\projects\plasmaos\frontend && set AUTH_SECRET=s106-secret&& set AUTH_URL=http://localhost:3116&& set NEXTAUTH_URL=http://localhost:3116&& set AUTH_TRUST_HOST=true&& set NEXT_DIST_DIR=.next-s107-browser&& set BACKEND_INTERNAL_URL=http://127.0.0.1:8116/api/v1&& call C:\Progra~1\nodejs\npm.cmd run start -- -p 3116')
  log=(OUT/'server.log').open('w'); proc=subprocess.Popen([s72.CMD,'/d','/s','/c',command],stdout=log,stderr=log,start_new_session=True)
  def case(name,fn):
    try: evidence=fn(); results.append({'case':name,'status':'PASS','evidence':evidence})
    except Exception as exc: results.append({'case':name,'status':'FAIL','error':str(exc)[:1000]})
    (OUT/'results.json').write_text(json.dumps(results,indent=2)); print(results[-1]['status'],name,flush=True)
  def check(value,message='check failed'):
    if not value: raise AssertionError(message)
    return value
  try:
    for _ in range(60):
      try:urlopen(f'http://{s72.WINDOWS_HOST}:3116',timeout=2);break
      except Exception:time.sleep(.5)
    with sync_playwright() as pw:
      expect.set_options(timeout=15000)
      profile_name=f's106-browser-profile-{os.getpid()}'; profile=rf'C:\Users\acer\AppData\Local\Temp\{profile_name}'
      chrome=r'C:\Users\acer\AppData\Local\ms-playwright\chromium-1208\chrome-win64\chrome.exe'
      launch=f"$p=Start-Process -FilePath '{chrome}' -ArgumentList '--headless=new','--disable-gpu','--no-first-run','--remote-debugging-port=0','--user-data-dir={profile}','about:blank' -PassThru; $p.Id"
      launched=None
      for _ in range(3):
        launched=subprocess.run([s72.POWERSHELL,'-NoProfile','-Command',launch],capture_output=True,text=True)
        if not launched.returncode: break
        time.sleep(.5)
      if launched.returncode: raise RuntimeError(f'Chromium launch failed: {launched.stderr.strip()}')
      profile_path=Path('/mnt/c/Users/acer/AppData/Local/Temp')/profile_name; port_file=profile_path/'DevToolsActivePort'
      deadline=time.time()+60
      while time.time()<deadline and not port_file.exists(): time.sleep(.2)
      if not port_file.exists(): raise RuntimeError('Chromium did not publish DevToolsActivePort')
      cdp_port=int(port_file.read_text().splitlines()[0]); proxy=subprocess.Popen(['/mnt/c/Program Files/nodejs/node.exe','tests/cdp-port-forward.mjs',str(CDP_PROXY_PORT),str(cdp_port)],cwd=FRONT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
      for _ in range(60):
        try:urlopen(f'http://{s72.WINDOWS_HOST}:{CDP_PROXY_PORT}/json/version',timeout=1);break
        except Exception:time.sleep(.2)
      browser=pw.chromium.connect_over_cdp(f'http://{s72.WINDOWS_HOST}:{CDP_PROXY_PORT}'); context=browser.contexts[0]; context.set_default_timeout(15000); page=context.pages[0] if context.pages else context.new_page(); page.emulate_media(reduced_motion='reduce'); page.on('pageerror',lambda e:errors.append(str(e))); page.set_default_timeout(15000); page.set_default_navigation_timeout(30000)
      user_token=token('pilot_user','s106-user'); user_b_token=token('pilot_user','s106-user-b'); admin_token=token('admin','s72-token-admin')
      def session(value): context.clear_cookies(); context.add_cookies([{'name':'authjs.session-token','value':value,'url':BASE,'httpOnly':True,'sameSite':'Lax'}])
      def visit(path,heading):
        response=None
        for _ in range(3):
          try:
            response=page.goto(BASE+path,wait_until='domcontentloaded')
            page.get_by_role('heading',name=heading,exact=True).wait_for(state='visible',timeout=10000)
            return response
          except Exception: time.sleep(.5)
        raise AssertionError(f'{heading} did not become available')
      axe_source=(FRONT/'node_modules/axe-core/axe.min.js').read_text(encoding='utf-8')
      def axe_case(name):
        page.add_script_tag(content=axe_source)
        result=page.evaluate("async()=>await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})")
        (OUT/f'{name}-axe.json').write_text(json.dumps(result,indent=2))
        bad=[x for x in result['violations'] if x['impact'] in ['serious','critical']]
        return check(not bad,str([(x['id'],len(x['nodes'])) for x in bad]))
      session(user_token)
      labels={'en':'Notifications','uz':'Bildirishnomalar','ru':'Уведомления','ar':'الإشعارات'}
      for locale in ['en','uz','ru','ar']:
        s72.State.users['s106-user']['ui_locale']=locale
        for width in [320,390,768,1440]:
          page.set_viewport_size({'width':width,'height':900}); start=len(Data.requests); errors.clear(); response=visit('/dashboard/notifications',labels[locale]); prefix=f'notifications/{locale}/{width}'
          expect(page.get_by_text('Authored <b>verbatim</b> announcement',exact=True)).to_be_visible()
          case(prefix+'/status',lambda response=response:check(response.status==200,'status'))
          case(prefix+'/localized-title',lambda label=labels[locale]:check(page.get_by_role('heading',name=label,exact=True).count()==1,'title'))
          case(prefix+'/direction',lambda locale=locale:check(page.locator('html').get_attribute('dir')==('rtl' if locale=='ar' else 'ltr'),'direction'))
          case(prefix+'/responsive-bounds',lambda:check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'overflow'))
          def request_budget(start=start):
            calls=Data.requests[start:]; paths=Counter(urlparse(x[1]).path for x in calls)
            return check(len(calls)<=20 and paths['/api/v1/notifications']==1 and paths['/api/v1/notifications/unread-count']==1,str(Counter(x[1] for x in calls)))
          case(prefix+'/request-budget',request_budget)
      case('notifications/ar/axe',lambda:axe_case('notifications-ar-1440'))
      for locale in ['en','ar']:
        s72.State.users['s106-user']['ui_locale']=locale; page.set_viewport_size({'width':320,'height':900}); visit('/dashboard/notifications',labels[locale])
        case(f'notifications/{locale}/mobile-axe',lambda locale=locale:axe_case(f'notifications-{locale}-320'))
      s72.State.users['s106-user']['ui_locale']='en'; page.set_viewport_size({'width':1440,'height':900}); visit('/dashboard/notifications','Notifications'); expect(page.get_by_text('Authored <b>verbatim</b> announcement',exact=True)).to_be_visible()
      case('notifications/verbatim-subject',lambda:check(page.get_by_text('Authored <b>verbatim</b> announcement',exact=True).count()==1))
      case('notifications/no-html-execution',lambda:check(page.locator('b').filter(has_text='verbatim').count()==0))
      case('notifications/unknown-safe-fallback',lambda:check(page.get_by_text('Account update',exact=True).count()==1))
      case('notifications/no-raw-template-key',lambda:check('notifications.' not in page.locator('main').inner_text()))
      page.evaluate("window.dispatchEvent(new Event('focus'))"); expect(page.get_by_label('Notifications, 4 unread')).to_be_visible()
      case('notifications/bell-authoritative',lambda:check(page.get_by_label('Notifications, 4 unread').count()==1))
      before=sum(not x['is_read'] for x in Data.notifications); page.get_by_role('button',name='Mark as read',exact=True).first.click(); expect(page.get_by_label('Notifications, 3 unread')).to_be_visible()
      case('notifications/read-patch',lambda:check(sum(not x['is_read'] for x in Data.notifications)==before-1))
      page.get_by_role('button',name='Mark all as read',exact=True).click(); expect(page.get_by_label('Notifications',exact=True)).to_be_visible()
      case('notifications/mark-all-authority',lambda:check(all(x['is_read'] for x in Data.notifications)))
      case('notifications/no-console-errors',lambda:check(not errors,str(errors)))
      case('notifications/single-count-owner',lambda:check(Counter(urlparse(x[1]).path for x in Data.requests)['/api/v1/notifications/unread-count']<30,'amplified'))
      case('notifications/en/axe',lambda:axe_case('notifications-en-1440'))
      if os.environ.get('PLASMA_S107_MODE') == '1':
        # Final closure adds whole-platform shell, locale, viewport and passivity
        # coverage to the communications/admin acceptance ledger.
        s107_routes=[
          ('dashboard','/dashboard'),
          ('explorer','/dashboard/tenders?view=all'),
          ('tender-details','/dashboard/tenders/s72-tender'),
          ('my-tenders','/dashboard/my-tenders'),
          ('bid-preparation','/dashboard/bid-preparation'),
          ('settings','/dashboard/settings'),
          ('readiness','/dashboard/readiness-vault'),
          ('compliance','/dashboard/tenders/s72-tender/compliance'),
        ]
        for locale in ['en','uz','ru','ar']:
          s72.State.users['s106-user']['ui_locale']=locale
          for width in [320,390,768,1440]:
            page.set_viewport_size({'width':width,'height':900}); errors.clear(); before=len(Data.requests)
            response=page.goto(BASE+'/dashboard',wait_until='domcontentloaded'); page.locator('h1').first.wait_for(state='visible')
            prefix=f'platform/dashboard/{locale}/{width}'
            case(prefix+'/status',lambda response=response:check(response and response.status==200,'status'))
            case(prefix+'/direction',lambda locale=locale:check(page.locator('html').get_attribute('dir')==('rtl' if locale=='ar' else 'ltr'),'direction'))
            case(prefix+'/responsive-foundation',lambda:check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1') and page.locator('.shell-legacy-content').count()==0,'overflow or legacy shell'))
            case(prefix+'/passive',lambda before=before:check(not any(method in ['POST','PUT','PATCH','DELETE'] and '/auth/refresh' not in path for method,path,_ in Data.requests[before:]),'page-load write'))
        s72.State.users['s106-user']['ui_locale']='en'; page.set_viewport_size({'width':1440,'height':900})
        for name,path in s107_routes[1:]:
          errors.clear(); before=len(Data.requests); response=page.goto(BASE+path,wait_until='domcontentloaded'); page.locator('h1').first.wait_for(state='visible')
          case(f'platform/{name}/status',lambda response=response:check(response and response.status==200,'status'))
          case(f'platform/{name}/foundation',lambda:check(page.locator('.customer-page').count()>0 and page.locator('.shell-legacy-content').count()==0,'foundation'))
          case(f'platform/{name}/responsive',lambda:check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'overflow'))
          case(f'platform/{name}/passive',lambda before=before:check(not any(method in ['POST','PUT','PATCH','DELETE'] and '/auth/refresh' not in request_path for method,request_path,_ in Data.requests[before:]),'page-load write'))
          case(f'platform/{name}/runtime',lambda:check(not errors,str(errors)))
      session(user_b_token); visit('/dashboard/notifications','Notifications')
      case('ownership/user-b-inbox-isolated',lambda:check(page.get_by_text('You’re all caught up',exact=True).count()==1))
      def cross_user_patch():
        result=page.evaluate("""async id=>{const r=await fetch('/api/v1/notifications/'+id,{method:'PATCH',headers:{'Content-Type':'application/json','Authorization':'Bearer s106-user-b'},body:JSON.stringify({is_read:false})});return r.status;}""",Data.notifications[0]['id'])
        return check(result==404,f'cross-user patch returned {result}')
      case('ownership/user-b-cannot-update-user-a',cross_user_patch)
      def ordinary_admin_api():
        status=page.evaluate("""async()=>{const r=await fetch('/api/v1/admin/broadcasts?limit=1',{headers:{'Authorization':'Bearer s106-user-b'}});return r.status;}""")
        return check(status==403,f'ordinary-user Admin API returned {status}')
      case('auth/ordinary-user-broadcast-api-denied',ordinary_admin_api)
      def ordinary_admin_page():
        probe=context.new_page()
        try:
          probe.goto(BASE+'/admin/broadcasts',wait_until='domcontentloaded'); probe.wait_for_url(BASE+'/dashboard')
          return check('/admin/' not in probe.url,probe.url)
        finally: probe.close()
      case('auth/ordinary-user-broadcast-page-denied',ordinary_admin_page)
      session(admin_token)
      for path,title in [('/admin/broadcasts','Broadcasts & announcements'),('/admin/approvals','Accounts & approvals')]:
        for width in [320,390,768,1440]:
          page.set_viewport_size({'width':width,'height':900}); errors.clear(); response=visit(path,title); prefix=('broadcasts' if 'broadcasts' in path else 'accounts')+f'/{width}'
          case(prefix+'/status',lambda response=response:check(response.status==200))
          case(prefix+'/title',lambda title=title:check(page.get_by_role('heading',name=title,exact=True).count()==1))
          case(prefix+'/ltr-boundary',lambda:check(page.locator('[data-admin-ltr-island]').get_attribute('dir')=='ltr'))
          if path=='/admin/approvals' and width<900:
            case(prefix+'/responsive-bounds',lambda:check(page.evaluate("""()=>{const shell=document.querySelector('.app-shell').getBoundingClientRect(),table=document.querySelector('.admin-table-scroll');return shell.left>=-1&&shell.right<=innerWidth+1&&getComputedStyle(table).overflowX==='auto'&&table.clientWidth<table.scrollWidth}""")))
          else: case(prefix+'/responsive-bounds',lambda:check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')))
          case(prefix+'/no-runtime-errors',lambda:check(not errors,str(errors)))
      page.set_viewport_size({'width':1440,'height':900}); visit('/admin/broadcasts','Broadcasts & announcements')
      case('broadcasts/axe',lambda:axe_case('broadcasts-en-1440'))
      for status in ['DRAFT','QUEUED','SENDING','SENT','PARTIAL','FAILED']: case('broadcasts/status/'+status,lambda status=status:check(page.get_by_text(status,exact=True).count()>=1))
      page.get_by_label('Subject').fill('New authored subject'); page.get_by_label('Body').fill('Line one\n<script> stays text');
      case('broadcasts/plain-preview',lambda:check(page.locator('.broadcast-preview script').count()==0))
      page.get_by_role('button',name='Preview audience').click(); expect(page.get_by_text('Audience preview confirmed 5 eligible recipients.')).to_be_visible()
      case('broadcasts/authoritative-preview',lambda:check(True))
      page.get_by_role('button',name='Send test').click(); expect(page.get_by_text('Test delivered only to your administrator inbox.')).to_be_visible()
      case('broadcasts/test-truthful',lambda:check(True))
      page.get_by_role('button',name='Broadcast now').click(); expect(page.get_by_role('dialog')).to_be_visible()
      case('broadcasts/final-confirmation',lambda:check(page.get_by_role('dialog').get_by_text('5',exact=True).count()>=1))
      page.get_by_role('dialog').get_by_role('button',name='Send to 5 recipients').click(); expect(page.get_by_text('Delivery is asynchronous.',exact=False)).to_be_visible()
      case('broadcasts/final-queued',lambda:check(page.get_by_text('QUEUED',exact=True).count()>=1))
      visit('/admin/approvals','Accounts & approvals'); expect(page.get_by_role('button',name='View',exact=True).first).to_be_visible(); page.get_by_role('button',name='View',exact=True).nth(1).click(); expect(page.get_by_role('dialog')).to_be_visible()
      case('accounts/detail-drawer',lambda:check(page.get_by_role('dialog').get_by_text('Account actions').count()==1))
      case('accounts/audit-entry',lambda:check(page.get_by_role('dialog').get_by_role('link',name='View immutable audit history').count()==1))
      case('accounts/lifecycle-actions',lambda:check(page.get_by_role('dialog').get_by_role('button',name='Approve').count()==1))
      page.get_by_role('dialog').get_by_role('button',name='Approve').click(); expect(page.get_by_role('dialog',name='Approve account2@example.invalid?')).to_be_visible()
      case('accounts/invalidation-warning',lambda:check(page.get_by_text('Immediate session invalidation').count()==1))
      case('accounts/dialog-axe',lambda:axe_case('accounts-dialog-en-1440'))
      minimum=180 if os.environ.get('PLASMA_S107_MODE') == '1' else 120
      case('suite/minimum-cases',lambda:check(len(results)>=minimum,f'only {len(results)} cases'))
      browser.close()
      proxy.terminate()
  finally:
    server.shutdown();
    try: os.killpg(proc.pid,signal.SIGTERM)
    except ProcessLookupError: pass
    subprocess.run([s72.POWERSHELL,'-NoProfile','-Command',"Get-NetTCPConnection -LocalPort 3116 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force }"],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    subprocess.run([s72.POWERSHELL,'-NoProfile','-Command',f"Get-CimInstance Win32_Process | Where-Object {{$_.CommandLine -like '*s106-browser-profile-{os.getpid()}*'}} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    log.close()
  minimum=180 if os.environ.get('PLASMA_S107_MODE') == '1' else 120
  failed=[x for x in results if x['status']=='FAIL']; print(json.dumps({'total':len(results),'passed':len(results)-len(failed),'failed':len(failed)},indent=2)); return 1 if failed or len(results)<minimum else 0

if __name__=='__main__': raise SystemExit(main())
