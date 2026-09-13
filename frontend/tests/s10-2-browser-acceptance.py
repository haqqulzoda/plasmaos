#!/usr/bin/env python3
"""Sprint 10.2: production Chromium against deterministic local, test-only API fixtures.
No real identity/source requests. Uses the same release build as the maintained gate.
"""
import importlib.util, json, os, signal, subprocess, threading, time, copy
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[2]
FRONT=Path(os.environ.get('PLASMA_FRONTEND_TEST_ROOT','/tmp/plasma-s101-release'))
OUT=ROOT/'docs/audits/s10_2/browser';BASE='http://localhost:3114'
def load(name,file):
 spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 fixture=load('s102_rtl','s8-3-arabic-rtl-browser-acceptance.py');details_fixture=load('s102_details','s7-3-p0-browser-acceptance.py');s72=fixture.s72
 s72.State.active=False;s72.State.users['s72-token-a'].update(ui_locale='en',default_analysis_language='uz')
 state={'mode':'populated','dismissed':False,'saved':False,'details_status':200};requests=[];external=[];errors=[];rows=[]
 titles=['Digital transformation services for public administration','Technical assistance for sustainable energy solutions','Inclusive economic development program']
 def tender(i=0):
  return {**s72.tender(),'id':'s72-tender' if i==0 else f's102-tender-{i}','title':titles[i],'budget':[12500000,4800000,3200000][i],'deadline':'2026-12-20T10:00:00Z','external_id':f'WB-2026-00{i+1}','is_new':True,'created_at':'2026-09-08T10:00:00Z','new_until':'2026-09-09T10:00:00Z'}
 def rec(i=0):return {'recommendation_id':f'rec-{i}','match_score':[92,78,85][i],'rationale_summary':'Stored recommendation rationale — النص الأصلي — исходный текст.','is_dismissed':state['dismissed'],'created_at':'2026-09-02T10:00:00Z'}
 class Handler(fixture.Handler):
  def do_GET(self):
   parsed=urlparse(self.path);path=parsed.path;q=parse_qs(parsed.query);requests.append(('GET',self.path))
   if state['mode']=='failure' and path in ['/api/v1/users/me/company','/api/v1/vault/readiness','/api/v1/tenders','/api/v1/explorer/tenders']:return self.send_json(503,{'detail':'fixture unavailable'})
   if state['mode']=='partial' and path=='/api/v1/vault/readiness':return self.send_json(503,{'detail':'fixture unavailable'})
   if path=='/api/v1/users/me/company':return self.send_json(200,{**s72.State.company,'company_profile_id':None if state['mode']=='profile' else 'shared-company','onboarding_required':state['mode']=='profile'})
   if path=='/api/v1/vault/readiness' and state['mode']=='empty':return self.send_json(200,[])
   if path=='/api/v1/tenders':return self.send_json(200,[] if state['mode']=='empty' else [tender()])
   if path=='/api/v1/explorer/tenders':
    view=q.get('view',['all'])[0];items=[{'tender':tender(i),'recommendation':rec(i),'pursuit':{'engagement_id':'engagement-s102','status':'SAVED','allowed_actions':['EVALUATE','PREPARE_BID','DISMISS']} if state['saved'] and i==0 else None} for i in range(3)]
    if state['mode']=='empty' or (view=='dismissed' and not state['dismissed']) or (view=='recommended' and state['dismissed']):items=[]
    return self.send_json(200,{'view':view,'items':items,'total':63 if items else 0,'limit':25,'offset':int(q.get('offset',['0'])[0]),'counts':{'all_tenders':63,'active_recommendations':0 if state['dismissed'] else 3,'dismissed_recommendations':3 if state['dismissed'] else 0},'recommendation_availability':'PROFILE_REQUIRED' if state['mode']=='profile' else 'AVAILABLE','server_time':'2026-09-08T10:00:00Z'})
   if path=='/api/v1/tenders/s72-tender':return self.send_json(state['details_status'],tender() if state['details_status']==200 else {'detail':'fixture error'})
   if path=='/api/v1/tenders/s72-tender/details':
    d=details_fixture.tender_details();d['recommendation']=rec();envelope=details_fixture.envelope
    d['project_context']=envelope({'project_id':'project-s102','external_project_id':'P176543','name':'Digital public administration program','source_system':'world_bank','project_status':'Active','country':'Uzbekistan','region':'Central Asia','approval_date':'2026-01-12','closing_date':'2026-12-30','enrichment_state':'successful','last_enriched_at':'2026-09-01T10:00:00Z'})
    d['project_leadership']=envelope({'items':[{'role_id':'role-s102','role_type':'PROJECT_LEADERSHIP','display_name':'Project Leader — قائد المشروع','native_role':'Task Team Leader','canonical_role':'TASK_TEAM_LEADER','source_system':'world_bank','source_url':None,'is_current':True,'first_observed_at':'2026-09-01T10:00:00Z','last_observed_at':'2026-09-02T10:00:00Z','ended_at':None}],'total_count':1,'returned_count':1,'truncated':False})
    d['procurement_contacts']=envelope({'buyer_agency':'Public Procurement Office','contact_person':'Procurement Contact — مسؤول المشتريات','email':'procurement@example.invalid','phone':'+998 71 000 00 00','address':'Tashkent','submission_method':'Electronic submission','submission_deadline':'2026-12-20T10:00:00Z','question_deadline':'2026-12-10T10:00:00Z','procedure_type':'Services','participation_instructions':'Original source instructions — تعليمات المصدر.','official_source_url':None,'document_access_notes':None,'source_type':'TENDER_SOURCE'})
    d['documents']=envelope({'items':[{'document_id':'document-s102','display_name':'Request for proposals.pdf','document_type':'notice','metadata_classification':'PUBLIC_SOURCE_METADATA','source_system':'world_bank','availability':'AVAILABLE','file_size':4096,'content_type':'application/pdf','created_at':'2026-09-02T10:00:00Z'},{'document_id':'missing-s102','display_name':'Missing annex.pdf','document_type':'annex','metadata_classification':'PUBLIC_SOURCE_METADATA','source_system':'world_bank','availability':'UNAVAILABLE','file_size':None,'content_type':None,'created_at':'2026-09-02T10:00:00Z'}],'visible_total_count':2,'returned_count':2,'omitted_unknown_count':0,'truncated':False,'download_authorization_separate':True})
    d['compliance']=envelope({'analysis_id':'analysis-s102','version_number':2,'execution_state':'COMPLETED','compliance_completeness':'PARTIAL','decision_label':'PARTIAL_MATCH','key_issue_count':3,'coverage_signal':'Partial document coverage','version_origin':'NATIVE','override_applied':False,'created_at':'2026-09-02T10:00:00Z','completed_at':'2026-09-02T10:00:00Z'})
    d['company_readiness']=envelope({'profile_available':True,'certifications_total':5,'expired_certifications':2,'licenses_total':4,'active_licenses':4,'credentials_total':8,'expired_credentials':2,'readiness_documents_total':12,'readiness_documents_available':7,'readiness_documents_missing':3,'readiness_documents_expired':2,'readiness_documents_unknown':0,'financial_history_years':3})
    return self.send_json(200,d)
   if path=='/api/v1/tenders/documents/document-s102/download':
    body=b'%PDF-1.4\n% deterministic local fixture\n%%EOF';self.send_response(200);self.send_header('Content-Type','application/pdf');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
   if path=='/api/v1/tenders/s72-tender/latest-analysis':
    return self.send_json(200,{'analysis_id':'analysis-s102','analysis_status':'completed','requirement_count':24,'manual_review_count':0,'created_at':'2026-09-08T08:00:00Z','coverage_metadata':{'coverage_status':'complete'}})
   return super().do_GET()
  def do_POST(self):
   requests.append(('POST',self.path));path=urlparse(self.path).path
   if path.startswith('/api/v1/recommendations/'):state['dismissed']=path.endswith('/dismiss');return self.send_json(200,{'status':'dismissed' if state['dismissed'] else 'restored','recommendation':rec()})
   if path=='/api/v1/tenders/s72-tender/engagement':state['saved']=True;return self.send_json(200,{'engagement':{'engagement_id':'engagement-s102','engagement_status':'SAVED','allowed_actions':['EVALUATE','PREPARE_BID','DISMISS']}})
   return super().do_POST()
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
 js="import {encode} from 'next-auth/jwt'; console.log(await encode({secret:'s72-browser-secret',salt:'__Secure-authjs.session-token',token:{name:'Synthetic Pilot',email:'pilot@example.invalid',sub:'72000000-0000-4000-8000-000000000001',accessToken:'s72-token-a',approval_status:'approved',platform_role:'pilot_user'},maxAge:3600}));"
 token=subprocess.check_output(['node','--input-type=module','-e',js],cwd=FRONT,env=env,text=True).strip()
 try:
  for _ in range(60):
   try:urlopen(BASE,timeout=2);break
   except Exception:time.sleep(1)
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,args=['--no-sandbox']);c=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce');c.add_cookies([{'name':'__Secure-authjs.session-token','value':token,'domain':'localhost','path':'/','secure':True}])
   def network(r):
    if urlparse(r.request.url).hostname not in ['localhost','127.0.0.1']:external.append(r.request.url);r.abort()
    else:r.continue_()
   c.route('**/*',network);page=c.new_page();page.set_default_timeout(6000);page.on('pageerror',lambda e:errors.append(str(e)))
   routes={'dashboard':'/dashboard','explorer':'/dashboard/tenders?view=all','tender-details':'/dashboard/tenders/s72-tender'}
   for locale in ['en','uz','ru','ar']:
    s72.State.users['s72-token-a']['ui_locale']=locale
    for width in [320,390,768,1024,1440]:
     page.set_viewport_size({'width':width,'height':1000})
     for name,path in routes.items():
      start=len(requests);errors.clear();response=page.goto(BASE+path,wait_until='networkidle');expect(page.locator('h1')).to_be_visible();page.wait_for_timeout(100)
      prefix=f'{name}/{locale}/{width}'
      case(prefix+'/render',lambda:check(response.status==200 and not errors,str(errors)))
      case(prefix+'/direction',lambda:check(page.locator('html').get_attribute('lang')==locale and page.locator('.customer-page').first.evaluate('(e)=>getComputedStyle(e).direction')==('rtl' if locale=='ar' else 'ltr'),'locale/direction mismatch'))
      case(prefix+'/overflow',lambda:check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'page overflow'))
      case(prefix+'/foundation',lambda:check(page.locator('.shell-legacy-content').count()==0 and page.locator('.ds-surface').count()>0,'legacy foundation'))
      def passive():
       calls=requests[start:];check(all(m=='GET' or p.startswith('/api/v1/auth/refresh') for m,p in calls),'unexpected write');counts=Counter(urlparse(p).path for _,p in calls);check(counts['/api/v1/users/me']<=8 and counts['/api/v1/users/me/access-status']<=4 and counts['/api/v1/auth/refresh']<=6 and len(calls)<=30,'request budget '+str(counts));return dict(counts)
      case(prefix+'/passivity-budget',passive)
      page.screenshot(path=str(OUT/f'{name}-{locale}-{width}.png'),full_page=True)
      if locale in ['en','ar'] and width in [390,1440]:
       def axe_check(prefix=prefix):
        page.add_script_tag(path=os.environ.get('PLASMA_AXE_PATH','/tmp/plasma-s101-qa/node_modules/axe-core/axe.min.js'));result=page.evaluate('async()=>await axe.run(document,{runOnly:{type:"tag",values:["wcag2a","wcag2aa","wcag21aa"]}})');(OUT/(prefix.replace('/','-')+'-axe.json')).write_text(json.dumps(result));bad=[v for v in result['violations'] if v['impact'] in ['serious','critical']];check(not bad,str([(v['id'],len(v['nodes'])) for v in bad]));return {'serious_critical':len(bad)}
       case(prefix+'/axe',axe_check)
   s72.State.users['s72-token-a']['ui_locale']='en';page.set_viewport_size({'width':1440,'height':1000})
   for mode in ['empty','partial','failure','profile']:
    def dashboard_state(mode=mode):
     state['mode']=mode;page.goto(BASE+'/dashboard',wait_until='networkidle');expect(page.locator('h1')).to_be_visible();text=page.locator('.customer-page').inner_text();check('could not be loaded' in text if mode=='failure' else 'Data unavailable' in text if mode=='partial' else 'No saved analyses found' in text if mode=='empty' else 'Dashboard' in text,'wrong state '+text[:200]);page.screenshot(path=str(OUT/f'dashboard-state-{mode}.png'),full_page=True)
    case('dashboard/state/'+mode,dashboard_state)
   state['mode']='populated'
   for view in ['all','recommended','dismissed']:
    def view_check(view=view):
     page.goto(BASE+'/dashboard/tenders?view='+view,wait_until='networkidle');check(page.get_by_role('tab',selected=True).count()==1,'tab selection');check(any('/explorer/tenders?' in p and ('view='+view) in p for _,p in requests[-12:]),'backend view code')
    case('explorer/view/'+view,view_check)
   for query in ['source=world_bank','new_only=true','q=digital','sort=deadline_soonest','page=2','document_status=files_missing','countries=Uzbekistan','services=it','category=services','price_min=1000','price_max=100000','deadline_status=active','status=unknown','region=Central+Asia']:
    def query_check(query=query):
     start=len(requests);page.goto(BASE+'/dashboard/tenders?view=all&'+query,wait_until='networkidle');backend=[p for _,p in requests[start:] if '/explorer/tenders?' in p];check(bool(backend),'missing query request');expected=parse_qs(query);actual=parse_qs(urlparse(backend[-1]).query)
     for key,val in expected.items():check(actual.get('offset' if key=='page' else key)==(['25'] if key=='page' else val),'query mismatch '+str(actual))
    case('explorer/query/'+query,query_check)
   for width in [390,1440]:
    def preview_check(width=width):
     page.set_viewport_size({'width':width,'height':1000});page.goto(BASE+'/dashboard/tenders?view=all',wait_until='networkidle');start=len(requests);page.get_by_role('button',name='Preview tender',exact=True).first.click();target=page.locator('dialog[open]') if width<1200 else page.locator('.explorer-rail');expect(target).to_contain_text(titles[0]);check(not any('/details' in p for _,p in requests[start:]),'preview fetched details');page.screenshot(path=str(OUT/f'explorer-preview-{width}.png'),full_page=True)
     if width<1200:page.keyboard.press('Escape');expect(page.locator('dialog[open]')).to_have_count(0);expect(page.get_by_role('button',name='Preview tender',exact=True).first).to_be_focused()
    case('explorer/preview/'+str(width),preview_check)
   page.set_viewport_size({'width':1440,'height':1000})
   def chips():
    page.goto(BASE+'/dashboard/tenders?view=all&countries=Uzbekistan',wait_until='networkidle');page.get_by_role('button',name='Remove Uzbekistan',exact=True).click();page.wait_for_url(lambda u:'countries=' not in u);check('countries=' not in page.url,'chip did not clear')
   case('explorer/removable-chip',chips)
   def search():
    page.goto(BASE+'/dashboard/tenders?view=all',wait_until='networkidle');page.get_by_role('searchbox').fill('digital');page.wait_for_url('**q=digital**');page.get_by_role('button',name='Clear search',exact=True).click();page.wait_for_url(lambda u:'q=' not in u);expect(page.get_by_role('searchbox')).to_be_focused()
   case('explorer/search-clear',search)
   def save():
    page.goto(BASE+'/dashboard/tenders?view=all',wait_until='networkidle');start=len(requests);page.get_by_role('button',name='Save to My Tenders',exact=True).first.click();page.wait_for_timeout(700);writes=[p for m,p in requests[start:] if m=='POST' and '/auth/' not in p];check(writes==['/api/v1/tenders/s72-tender/engagement'],str(writes))
   case('explorer/save-pursuit-only',save)
   def dismiss():
    page.goto(BASE+'/dashboard/tenders?view=recommended',wait_until='networkidle');page.get_by_role('button',name='Dismiss recommendation',exact=True).first.click();page.wait_for_timeout(500);check(state['dismissed'],'not dismissed');page.goto(BASE+'/dashboard/tenders?view=dismissed',wait_until='networkidle');page.get_by_role('button',name='Restore recommendation',exact=True).first.click();page.wait_for_timeout(500);check(not state['dismissed'],'not restored')
   case('explorer/recommendation-dismiss-restore',dismiss)
   for status in [404,403,503]:
    def detail_error(status=status):
     state['details_status']=status;page.goto(BASE+'/dashboard/tenders/s72-tender',wait_until='networkidle');expect(page.locator('.customer-page').get_by_role('alert')).to_contain_text('Tender not found' if status==404 else 'do not have access' if status==403 else 'could not');page.screenshot(path=str(OUT/f'details-error-{status}.png'))
    case('details/error/'+str(status),detail_error)
   state['details_status']=200
   for anchor in ['pursuit','project-context','requirements-documents','compliance-readiness','contacts','bid-preparation']:
    def anchor_check(anchor=anchor):
     page.goto(BASE+'/dashboard/tenders/s72-tender',wait_until='networkidle');page.locator(f'nav a[href="#{anchor}"]').click();check(page.url.endswith('#'+anchor),'wrong anchor');expect(page.locator('#'+anchor)).to_be_visible()
    case('details/anchor/'+anchor,anchor_check)
   def stored_details():
    page.goto(BASE+'/dashboard/tenders/s72-tender',wait_until='networkidle');expect(page.locator('#project-context')).to_contain_text('Task Team Leader');expect(page.locator('#contacts')).to_contain_text('Procurement Contact');expect(page.locator('#contacts dd').filter(has_text='procurement@example.invalid')).to_have_attribute('dir','ltr');expect(page.locator('#requirements-documents')).to_contain_text('AI evidence sentence');expect(page.locator('#compliance-readiness')).to_contain_text('Partial');check(not any('/download' in p for _,p in requests[-12:]),'implicit document download')
   case('details/stored-project-contacts-analysis-boundaries',stored_details)
   def download():
    start=len(requests);button=page.locator('#requirements-documents').get_by_role('button',name='Open document',exact=True);button.click();page.wait_for_timeout(500);check(sum('/documents/document-s102/download' in p for _,p in requests[start:])==1,'explicit download missing');check(not external,'external download');expect(page.locator('#requirements-documents').get_by_role('button',name='Metadata only',exact=True)).to_be_disabled()
   case('details/explicit-local-document-download',download)
   def keyboard_tabs():
    page.goto(BASE+'/dashboard/tenders?view=all',wait_until='networkidle');page.get_by_role('tab',selected=True).focus();page.keyboard.press('ArrowRight');page.wait_for_url('**view=recommended**');expect(page.get_by_role('tab',selected=True)).to_be_focused()
   case('explorer/keyboard-tabs',keyboard_tabs)
   # Exercise the production locale transaction on each mounted page. The only
   # visible selector lives in Settings; this contract probe uses the current
   # AppRouter context to refresh without remounting the page under test.
   for name,path in routes.items():
    s72.State.active=True;s72.State.users['s72-token-a']['ui_locale']='en'
    page.goto(BASE+path,wait_until='networkidle');page.locator('[data-customer-shell]').evaluate('(e)=>e.dataset.continuity="s102"')
    if name=='explorer':page.get_by_role('button',name='Preview tender',exact=True).first.click()
    for locale in ['ar','ru']:
     def locale_change(locale=locale,name=name,path=path):
      original=page.url;start=len(requests)
      page.evaluate("""async locale=>{
        const session=await (await fetch('/api/auth/session')).json();
        const response=await fetch('/api/v1/users/me/preferences',{method:'PATCH',headers:{'Content-Type':'application/json','Authorization':'Bearer '+session.accessToken},body:JSON.stringify({ui_locale:locale})});
        if(!response.ok)throw new Error('preference failed');
        await fetch('/api/ui-locale',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ui_locale:locale})});
        const node=document.querySelector('[data-customer-shell]');
        let fiber=node[Object.keys(node).find(k=>k.startsWith('__reactFiber'))];
        while(fiber){const value=fiber.memoizedProps?.value;if(value && typeof value.refresh==='function' && typeof value.push==='function'){value.refresh();return;}fiber=fiber.return;}
        throw new Error('AppRouter context unavailable');
      }""",locale)
      expect(page.locator('html')).to_have_attribute('lang',locale);expect(page.locator('[data-customer-shell]')).to_have_attribute('data-continuity','s102');check(page.url==original,'route/query lost');expect(page.locator('.shell-refresh-control')).to_contain_text('World Bank');check(s72.State.users['s72-token-a']['default_analysis_language']=='uz','analysis preference changed');check(s72.State.max_activity_in_flight<=1,'duplicate poller')
      if name=='explorer':expect(page.locator('[data-tender-id="s72-tender"]')).to_have_attribute('data-selected','true')
      check(not any('/latest-analysis' in p or '/details' in p for _,p in requests[start:]),'locale reloaded domain reads')
      return {'route':original,'locale':locale,'shell':'preserved','max_poller':s72.State.max_activity_in_flight}
     case(f'continuity/{name}/en-to-{locale}',locale_change)
   s72.State.active=False
   def anonymous():
    ac=browser.new_context();ap=ac.new_page();ap.goto(BASE+'/dashboard',wait_until='networkidle');check('/dashboard' not in ap.url,'anonymous access');ac.close()
   case('auth/anonymous-denial',anonymous)
   case('network/no-external-requests',lambda:check(not external,str(external)))
   browser.close()
 finally:
  os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=15);server.shutdown();log.close();(OUT/'results.json').write_text(json.dumps(rows,indent=2))
 passed=sum(r['status']=='PASS' for r in rows);print(f'{passed}/{len(rows)} PASS')
 if passed!=len(rows):raise SystemExit(1)
if __name__=='__main__':main()
