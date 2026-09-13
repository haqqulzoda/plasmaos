#!/usr/bin/env python3
"""Sprint 10.4 Chromium acceptance against local production build and synthetic APIs.
Real PostgreSQL ownership/write fingerprints are a separate backend test gate.
"""
import importlib.util,json,os,signal,subprocess,threading,time,copy,re
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from urllib.request import urlopen
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[2];FRONT=Path(os.environ.get('PLASMA_FRONTEND_TEST_ROOT','/tmp/plasma-s102-final'));OUT=ROOT/'docs/audits/s10_4/browser';BASE='http://localhost:3114'
def load(name,file):
 spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
 OUT.mkdir(parents=True,exist_ok=True);fixture=load('s104_rtl','s8-3-arabic-rtl-browser-acceptance.py');s72=fixture.s72;s82=fixture.s82
 s72.State.active=False;s72.State.onboarding_required=False;s72.State.users['s72-token-a'].update(ui_locale='en',default_analysis_language='uz')
 company=copy.deepcopy(s72.State.company);company.update(pilot_status='active_pilot',company_name='Institutional Engineering Group',industry='Engineering and consulting',address='Tashkent — Toshkent — Ташкент',target_services=['consulting'])
 records=[{'id':f'record-{i}','company_profile_id':'shared-company','document_type':['license','certificate','financial_statement'][i%3],'document_name':['Construction License','ISO 9001:2015','Audited Financial Statements'][i%3]+f' {i+1}','document_number':f'REG-{i:03}','issuer':'Original Issuer — مصدر','issue_date':'2025-01-12','expiry_date':['2028-01-12','2026-09-20','2024-01-12'][i%3],'status':['available','unknown','expired','missing'][i%4],'related_service':'consulting','notes':'Original company record','optional_file_url':'https://files.example.invalid/stored.pdf' if i%2 else None} for i in range(31)]
 versions={i:s82.response_for(lang,i) for i,lang in enumerate(['en','uz','ru','en'],1)};versions[4]['analysis_language']=None
 for i,result in versions.items():
  result['coverage_metadata']={'coverage_status':'partial' if i==3 else 'complete'}
  detail=copy.deepcopy(result['hybrid_compliance']['manual_reviews_required'][0]);detail.update(verdict='FAILED',is_dealbreaker=True,headline='Minimum annual turnover',reason='Recorded turnover is below the stated requirement.')
  result['hybrid_compliance'].update(failed_dealbreakers=[detail],failed_count=1,total_requirements=2,verdict_status='NOT_ELIGIBLE')
 state={'mode':'populated','latest':3,'fail_write':False,'fail_analysis':False,'fail_version':False,'failed_result':False};requests=[];external=[];errors=[];rows=[];writes=[]
 def snapshot():return json.dumps([company,records,versions],sort_keys=True)
 def metadata(i):return {'analysis_id':'analysis-a','version_number':i,'analysis_language':versions[i]['analysis_language'],'origin':'GENERATED','status':'FAILED' if versions[i].get('analysis_status')=='failed' else 'COMPLETED','snapshot_completeness':'LEGACY_PARTIAL' if i==4 else 'COMPLETE','created_at':'2026-09-01T10:00:00Z','completed_at':'2026-09-01T10:01:00Z'}
 class Handler(fixture.Handler):
  def paged(self,items,q):
   offset=int(q.get('offset',['0'])[0]);body=json.dumps(items[offset:offset+25]).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('X-Total-Count',str(len(items)));self.send_header('X-Has-More',str(offset+25<len(items)).lower());self.end_headers();self.wfile.write(body)
  def do_GET(self):
   parsed=urlparse(self.path);path=parsed.path;q=parse_qs(parsed.query);requests.append(('GET',self.path))
   domain=path in ['/api/v1/users/me/company','/api/v1/vault/readiness'] or path.endswith('/latest-analysis')
   if domain and state['mode'] in ['failure','denied']:return self.send_json(503 if state['mode']=='failure' else 403,{'detail':'fixture unavailable'})
   if path=='/api/v1/users/me/company':return self.send_json(200,{**company,**({'company_name':'','industry':'','target_regions':[],'target_countries':[],'target_services':[]} if state['mode']=='empty' else {})})
   if path=='/api/v1/vault/readiness':
    items=records if state['mode']!='empty' else []
    for key in ['document_type','status','related_service']:
     if q.get(key):items=[x for x in items if x[key]==q[key][0]]
    return self.paged(items,q)
   if path=='/api/v1/tenders/s72-tender/latest-analysis':return self.send_json(200,versions[state['latest']] if state['mode']!='empty' else {'analysis_id':None,'requirements':None,'evaluation':None})
   if path=='/api/v1/tenders/s72-tender/analyses/analysis-a/versions':return self.paged([metadata(i) for i in sorted(versions,reverse=True)],q)
   match=re.fullmatch('/api/v1/tenders/s72-tender/analyses/analysis-a/versions/(\\d+)',path)
   if match:
    i=int(match[1])
    if state['fail_version'] or i not in versions:return self.send_json(503,{'detail':'unavailable'})
    return self.send_json(200,{'metadata':metadata(i),'result_snapshot':versions[i],'integrity':{'snapshot_completeness':metadata(i)['snapshot_completeness']}})
   if path=='/api/v1/tenders/s72-tender/overrides':return self.send_json(200,{'accepted_node_ids':[]})
   if path=='/api/v1/tenders/s72-tender/documents':return self.send_json(200,[])
   if path=='/api/v1/tenders/s72-tender/compliance/export/pdf':
    i=int(q.get('version_number',['0'])[0]);lang=versions.get(i,{}).get('analysis_language')
    if lang=='ar':return self.send_json(422,{'detail':'arabic_pdf_unavailable'})
    body=b'%PDF-1.4 fixture exact version';self.send_response(200);self.send_header('Content-Type','application/pdf');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
   if '/foreign-' in path:return self.send_json(404,{'detail':'not found'})
   return super().do_GET()
  def do_PUT(self):
   requests.append(('PUT',self.path));body=self.body();writes.append(('PUT',self.path,body))
   if state['fail_write']:return self.send_json(503,{'detail':'save unavailable'})
   if self.path=='/api/v1/users/me/company':company.update(body);return self.send_json(200,company)
   row=next((r for r in records if self.path=='/api/v1/vault/readiness/'+r['id']),None)
   if row:row.update(body);return self.send_json(200,row)
   return self.send_json(404,{'detail':'not found'})
  def do_DELETE(self):
   requests.append(('DELETE',self.path));row=next((r for r in records if self.path=='/api/v1/vault/readiness/'+r['id']),None)
   if state['fail_write']:return self.send_json(503,{'detail':'unavailable'})
   if row:records.remove(row);return self.send_json(200,{})
   return self.send_json(404,{'detail':'not found'})
  def do_POST(self):
   path=urlparse(self.path).path;requests.append(('POST',self.path))
   if path=='/api/v1/vault/readiness':
    body=self.body();writes.append(('POST',path,body))
    if state['fail_write']:return self.send_json(503,{'detail':'unavailable'})
    row={**body,'id':'record-new','company_profile_id':'shared-company'};records.insert(0,row);return self.send_json(201,row)
   if path=='/api/v1/tenders/s72-tender/analyze':
    lang=parse_qs(urlparse(self.path).query).get('analysis_language',[''])[0]
    if lang not in ['en','uz','ru']:return self.send_json(422,{'detail':'unsupported language'})
    if state['fail_analysis']:return self.send_json(503,{'detail':'unavailable'})
    i=max(versions)+1;versions[i]=s82.response_for(lang,i);state['latest']=i
    if state['failed_result']:versions[i]['analysis_status']='failed'
    return self.send_json(200,versions[i])
   if path=='/api/v1/tenders/s72-tender/override':
    body=self.body();writes.append(('POST',path,body));return self.send_json(200,{'override_seal':'a'*64,'overridden_node_ids':[body['node_id']],'state_hash':'b'*64})
   return super().do_POST()
  def do_PATCH(self):
   requests.append(('PATCH',self.path))
   if state['fail_write'] and self.path=='/api/v1/users/me/preferences':self.body();return self.send_json(503,{'detail':'unavailable'})
   return super().do_PATCH()
 server=ThreadingHTTPServer(('127.0.0.1',8114),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 env={**os.environ,'AUTH_SECRET':'s72-browser-secret','AUTH_URL':BASE,'NEXTAUTH_URL':BASE,'AUTH_TRUST_HOST':'true','NEXT_DIST_DIR':'.next-release-test','BACKEND_INTERNAL_URL':'http://127.0.0.1:8114/api/v1'}
 log=(OUT/('visual-server.log' if os.environ.get('PLASMA_S104_VISUAL_ONLY')=='1' else 'server.log')).open('w');proc=subprocess.Popen(['npm','run','start','--','-p','3114'],cwd=FRONT,env=env,stdout=log,stderr=log,start_new_session=True)
 def check(c,m):
  if not c:raise AssertionError(m)
 def case(name,fn):
  try:e=fn();rows.append({'case':name,'status':'PASS','evidence':e})
  except Exception as e:rows.append({'case':name,'status':'FAIL','error':str(e)[:1800]})
  state['fail_write']=False;state['fail_analysis']=False;state['fail_version']=False;state['failed_result']=False
  (OUT/'results.json').write_text(json.dumps(rows,indent=2))
  print(rows[-1]['status'],name,rows[-1].get('error','')[:200],flush=True)
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
   c.route('**/*',network);page=c.new_page();page.set_default_timeout(15000);page.set_default_navigation_timeout(30000);expect.set_options(timeout=15000);page.on('pageerror',lambda e:errors.append(str(e)))
   routes={'profile':'/dashboard/settings','readiness':'/dashboard/readiness-vault','compliance':'/dashboard/tenders/s72-tender/compliance'}
   def visit(path):return page.goto(BASE+path,wait_until='networkidle')
   def axe_check(name):
    page.add_script_tag(path='/tmp/plasma-s101-qa/node_modules/axe-core/axe.min.js');result=page.evaluate('async()=>await axe.run(document,{runOnly:{type:"tag",values:["wcag2a","wcag2aa","wcag21aa"]}})');(OUT/(name+'-axe.json')).write_text(json.dumps(result));bad=[v for v in result['violations'] if v['impact'] in ['serious','critical']];check(not bad,str([(v['id'],len(v['nodes'])) for v in bad]));return {'serious_critical':len(bad)}
   if os.environ.get('PLASMA_S104_VISUAL_ONLY')=='1':
    s72.State.users['s72-token-a']['ui_locale']='en';page.set_viewport_size({'width':1536,'height':1024})
    for name,path in routes.items():
     visit(path);expect(page.locator('h1')).to_be_visible();page.screenshot(path=str(OUT/f'{name}-en-1536.png'),full_page=True)
     if name=='readiness':
      page.get_by_role('button',name='Edit Construction License 1',exact=True).click();expect(page.locator('dialog[open]')).to_be_visible();page.screenshot(path=str(OUT/'readiness-edit-en-1536.png'));page.keyboard.press('Escape')
      page.get_by_role('button',name='Add record',exact=True).click();expect(page.locator('dialog[open]')).to_be_visible();page.screenshot(path=str(OUT/'readiness-add-en-1536.png'));page.keyboard.press('Escape')
     if name=='compliance':
      page.get_by_role('button',name='Override system flag',exact=True).click();expect(page.locator('dialog[open]')).to_be_visible();page.get_by_label('Justification',exact=True).fill('Recorded company evidence requires this explicit decision.');page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(OUT/'compliance-override-en-1536.png'));page.keyboard.press('Escape')
      page.locator('.compliance-requirement').first.get_by_role('button',name='Source evidence',exact=True).click();expect(page.locator('dialog[open]')).to_be_visible();page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(OUT/'compliance-evidence-en-1536.png'));page.keyboard.press('Escape')
    check(not errors,str(errors));browser.close();return
   for locale in ['en','uz','ru','ar']:
    s72.State.users['s72-token-a']['ui_locale']=locale
    for width in [320,390,768,1440]:
     page.set_viewport_size({'width':width,'height':1000})
     for name,path in routes.items():
      start=len(requests);errors.clear();before=snapshot();response=visit(path);expect(page.locator('h1')).to_be_visible();prefix=f'{name}/{locale}/{width}'
      case(prefix+'/render',lambda:check(response.status==200 and not errors,str(errors)))
      case(prefix+'/direction',lambda:check(page.locator('html').get_attribute('lang')==locale and page.locator('.customer-page').evaluate('(e)=>getComputedStyle(e).direction')==('rtl' if locale=='ar' else 'ltr'),'direction'))
      case(prefix+'/bounds',lambda:check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1') and page.locator('.customer-page').evaluate('(e)=>[...e.querySelectorAll("button,select,input")].filter(x=>x.checkVisibility()).every(x=>{const r=x.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1;})'),'overflow'))
      if name=='compliance' and width<768:
       def readable_controls():
        check(page.locator('.compliance-toolbar select').evaluate('(e)=>e.getBoundingClientRect().width>=200'),'run language too narrow')
        check(page.locator('.compliance-history select').evaluate('(e)=>e.getBoundingClientRect().width>=200'),'history too narrow')
        check(page.locator('.compliance-section .ds-section-header').first.evaluate('''e=>{const a=e.querySelector('h2').getBoundingClientRect(),b=e.querySelector('.ds-badge').getBoundingClientRect();return a.right<=b.left||a.left>=b.right||a.bottom<=b.top||a.top>=b.bottom;}'''),'assessment heading overlaps badge')
       case(prefix+'/readable-controls',readable_controls)
      case(prefix+'/foundation',lambda:check(page.locator('.shell-legacy-content').count()==0 and page.locator('.ds-surface').count()>0,'legacy wrapper'))
      def passive():
       calls=requests[start:];counts=Counter(urlparse(p).path for _,p in calls);check(all(m=='GET' or p.startswith('/api/v1/auth/refresh') for m,p in calls),'passive write');check(len(calls)<=35,'request budget '+str(counts));check(all(counts[p]<=1 for p in ['/api/v1/users/me/company','/api/v1/vault/readiness','/api/v1/tenders/s72-tender/latest-analysis','/api/v1/tenders/s72-tender/documents']),'duplicate domain read');check(before==snapshot(),'fixture domain changed');check(not any('/document-preview/' in p or '/analyze?' in p for _,p in calls),'implicit action');return dict(counts)
      case(prefix+'/passivity-budget',passive)
      case(prefix+'/content',lambda name=name:check(('Institutional Engineering Group' in page.locator('.customer-page').inner_text()) if name=='profile' else ('Original Issuer' in page.locator('.customer-page').inner_text()) if name=='readiness' else (s82.SOURCE_QUOTE in page.locator('.customer-page').inner_text()),'original content absent'))
      page.screenshot(path=str(OUT/f'{name}-{locale}-{width}.png'),full_page=True)
      if locale in ['en','ar'] and width in [390,1440]:case(prefix+'/axe',lambda prefix=prefix:axe_check(prefix.replace('/','-')))
   s72.State.users['s72-token-a']['ui_locale']='en';page.set_viewport_size({'width':1440,'height':1000})
   for name,path in routes.items():
    for mode in ['empty','failure','denied']:
     def states(name=name,path=path,mode=mode):
      state['mode']=mode;visit(path);check(page.locator('.customer-page').get_by_role('alert').count()>0 if mode!='empty' else page.locator('.customer-page').count()==1,'state');page.screenshot(path=str(OUT/f'{name}-{mode}.png'),full_page=True)
     case(name+'/state/'+mode,states)
    state['mode']='populated'
   visit(routes['profile'])
   def profile_save():
    before=json.dumps([records,versions],sort_keys=True);page.get_by_label('Company name',exact=True).fill('Updated Company');page.get_by_role('button',name='Save profile',exact=True).click();expect(page.locator('.profile-summary')).to_contain_text('Updated Company');check(company['company_name']=='Updated Company' and before==json.dumps([records,versions],sort_keys=True),'write boundary');check('default_analysis_language' not in writes[-1][2],'preference leaked')
   case('profile/save-domain-boundary',profile_save)
   def profile_failure():
    state['fail_write']=True;page.get_by_label('Company name',exact=True).fill('Unsaved Company');page.get_by_role('button',name='Save profile',exact=True).click();expect(page.locator('.customer-page').get_by_role('alert')).to_contain_text('could not be saved');check(company['company_name']=='Updated Company','false canonical save');page.get_by_role('button',name='Cancel changes',exact=True).click();expect(page.get_by_label('Company name',exact=True)).to_have_value('Updated Company');state['fail_write']=False
   case('profile/failure-cancel',profile_failure)
   for index,value,key in [(0,'Europe','target_regions'),(1,'Uzbekistan','target_countries'),(2,'Consulting','target_services')]:
    def taxonomy(index=index,value=value,key=key):
     before=snapshot();box=page.locator('.profile-options').nth(index).get_by_role('checkbox',name=value,exact=True);was=box.is_checked();box.set_checked(not was);check(box.is_checked()!=was and snapshot()==before,'checkbox state/passivity');
     with page.expect_response(lambda r:'/users/me/company' in r.url and r.request.method=='PUT') as response:page.get_by_role('button',name='Save profile',exact=True).click()
     check(response.value.status==200,'profile save response');expect(page.get_by_role('button',name='Save profile',exact=True)).to_be_enabled();canonical='consulting' if key=='target_services' else value;check((canonical in company[key]) != was,'canonical taxonomy payload')
    case('profile/taxonomy/'+key,taxonomy)
   def preference():
    before=snapshot();page.get_by_label('Analysis language',exact=True).select_option('ru');
    with page.expect_response(lambda r:'/users/me/preferences' in r.url and r.request.method=='PATCH'):page.get_by_role('button',name='Save analysis language',exact=True).click()
    expect(page.locator('.customer-page')).to_contain_text('Analysis language saved');check(s72.State.users['s72-token-a']['default_analysis_language']=='ru' and snapshot()==before,'preference ownership')
   case('profile/default-language-independent-save',preference)
   def preference_failure():
    state['fail_write']=True;page.get_by_label('Analysis language',exact=True).select_option('en');page.get_by_role('button',name='Save analysis language',exact=True).click();expect(page.get_by_label('Analysis language',exact=True)).to_have_value('ru');state['fail_write']=False
   case('profile/default-language-failure',preference_failure)
   visit(routes['readiness'])
   for field,value in [('Document type','license'),('Status','expired'),('Related service','consulting')]:
    def filter_case(field=field,value=value):
     with page.expect_response(lambda r:'/vault/readiness?' in r.url and value in r.url):page.locator('.readiness-filters').get_by_label(field,exact=True).select_option(value)
     expect(page.locator('.readiness-page [aria-label="Loading readiness records"]')).to_have_count(0)
     with page.expect_response(lambda r:'/vault/readiness?' in r.url):page.get_by_role('button',name='Reset filters',exact=True).click()
     expect(page.locator('.readiness-record')).to_have_count(25)

    case('readiness/filter/'+value,filter_case)
   def paging():
    page.get_by_role('button',name='Next',exact=True).click();expect(page.locator('.readiness-record')).to_have_count(6);expect(page.get_by_role('button',name='Next',exact=True)).to_be_disabled();page.get_by_role('button',name='Previous',exact=True).click();expect(page.locator('.readiness-record')).to_have_count(25)
   case('readiness/bounded-pagination',paging)
   def create():
    before=json.dumps(versions,sort_keys=True);page.get_by_role('button',name='Add record',exact=True).click();page.get_by_label('Document name',exact=True).fill('New canonical record');page.get_by_role('button',name='Save record',exact=True).click();expect(page.locator('dialog[open]')).to_have_count(0);expect(page.locator('.readiness-grid')).to_contain_text('New canonical record');check(len(records)==32 and versions and before==json.dumps(versions,sort_keys=True),'readiness write boundary')
   case('readiness/create-metadata-only',create)
   def edit():
    page.get_by_role('button',name='Edit New canonical record',exact=True).click();page.get_by_label('Issuer',exact=True).fill('Updated issuer');page.get_by_role('button',name='Save record',exact=True).click();expect(page.locator('.readiness-grid')).to_contain_text('Updated issuer')
   case('readiness/edit-owned-record',edit)
   def delete():
    page.get_by_role('button',name='Delete New canonical record',exact=True).click();expect(page.locator('dialog[open]')).to_be_visible();page.get_by_role('button',name='Delete record',exact=True).click();expect(page.locator('dialog[open]')).to_have_count(0);check(len(records)==31,'delete count')
   case('readiness/confirmed-delete',delete)
   for locale in ['en','ar']:
    s72.State.users['s72-token-a']['ui_locale']=locale;page.set_viewport_size({'width':390,'height':1000});visit(routes['readiness'])
    def drawer(locale=locale):
     page.locator('.ds-page-header button').click();expect(page.locator('dialog[open]')).to_be_visible();page.screenshot(path=str(OUT/f'readiness-drawer-{locale}.png'),full_page=True);axe_check('readiness-drawer-'+locale);page.set_viewport_size({'width':1440,'height':1000});page.screenshot(path=str(OUT/f'readiness-drawer-{locale}-1440.png'),full_page=True);page.keyboard.press('Escape');expect(page.locator('dialog[open]')).to_have_count(0);check(page.locator('.ds-page-header button').evaluate('(e)=>e===document.activeElement'),'drawer focus')
    case('readiness/drawer-axe-focus/'+locale,drawer)
   s72.State.users['s72-token-a']['ui_locale']='en';page.set_viewport_size({'width':1440,'height':1000});visit(routes['compliance'])
   for i in [1,2,3,4]:
    def version_case(i=i):
     before=snapshot();start=len(requests);page.get_by_role('combobox',name='Version history',exact=True).select_option(str(i));expect(page.get_by_role('combobox',name='Version history',exact=True)).to_have_value(str(i));page.wait_for_load_state('networkidle');check(snapshot()==before and not any(m!='GET' and '/auth/refresh' not in p for m,p in requests[start:]),'version mutation');expected=versions[i]['analysis_language'];check(page.locator('.compliance-narrative').get_attribute('dir')==('auto' if expected is None else 'ltr'),'stored language direction');page.screenshot(path=str(OUT/f'compliance-version-{i}.png'),full_page=True)
    case('compliance/exact-version/'+str(i),version_case)
   def version_failure():
    state['fail_version']=True;page.get_by_role('combobox',name='Version history',exact=True).select_option('2');expect(page.locator('.customer-page').get_by_role('alert')).to_contain_text('previous selection');expect(page.get_by_role('combobox',name='Version history',exact=True)).to_have_value('4');state['fail_version']=False
   case('compliance/version-failure-preserves-selection',version_failure)
   def run_failure():
    state['fail_analysis']=True;before=snapshot();page.get_by_role('button',name='Analyze again',exact=True).click();expect(page.locator('.customer-page').get_by_role('alert')).to_contain_text('could not be completed');expect(page.locator('.compliance-narrative')).to_be_visible();check(snapshot()==before,'failed run mutation');state['fail_analysis']=False
   case('compliance/failed-run-preserves-version',run_failure)
   for lang in ['en','uz','ru']:
    def run(lang=lang):
     before=json.dumps([company,records],sort_keys=True);page.get_by_label('Analysis language',exact=True).select_option(lang);page.get_by_role('button',name='Analyze again',exact=True).click();page.wait_for_load_state('networkidle');expect(page.locator('.compliance-requirement h3').first).to_contain_text(s82.localized(lang)[0]);check(before==json.dumps([company,records],sort_keys=True),'analysis domain boundary')
    case('compliance/explicit-run/'+lang,run)
   def failed_result():
    previous=page.get_by_role('combobox',name='Version history',exact=True).input_value();state['failed_result']=True;page.get_by_role('button',name='Analyze again',exact=True).click();expect(page.locator('.customer-page').get_by_role('alert')).to_contain_text('could not be completed');expect(page.get_by_role('combobox',name='Version history',exact=True)).to_have_value(previous);check(page.locator('.compliance-narrative').count()==1,'last result discarded');state['latest']=int(previous)
   case('compliance/failed-result-http200-preserves-version',failed_result)
   def evidence():
    start=len(requests);page.locator('.compliance-requirement').first.get_by_role('button',name='Source evidence',exact=True).click();expect(page.locator('dialog[open]')).to_contain_text(s82.SOURCE_QUOTE);check(not any('/document-preview/' in p for _,p in requests[start:]),'unmatched document retrieval');page.screenshot(path=str(OUT/'compliance-evidence.png'),full_page=True);axe_check('compliance-evidence');page.keyboard.press('Escape');expect(page.locator('dialog[open]')).to_have_count(0)
   case('compliance/evidence-original-explicit',evidence)
   def viewer():
    page.locator('.compliance-toolbar').get_by_role('button',name='Tender document',exact=True).click();expect(page.locator('[data-document-viewer]')).to_contain_text(s82.SOURCE_QUOTE);page.keyboard.press('Escape')
   case('compliance/local-document-viewer',viewer)
   def export():
    start=len(requests)
    with page.expect_download():page.get_by_role('button',name='Download Compliance PDF',exact=True).click()
    check(any('analysis_id=analysis-a' in p and 'version_number='+str(state['latest']) in p for _,p in requests[start:]),'export version')
   case('compliance/exact-version-export',export)
   versions[90]={**s82.response_for('en',90),'analysis_language':'ar'};state['latest']=90;visit(routes['compliance'])
   case('compliance/arabic-pdf-gate',lambda:expect(page.get_by_role('button',name='Download Compliance PDF',exact=True)).to_be_disabled())
   case('compliance/arabic-run-unselectable',lambda:check('ar' not in page.get_by_label('Analysis language',exact=True).locator('option').evaluate_all('(es)=>es.map(e=>e.value)'),'Arabic selectable'))
   state['latest']=3
   for lang,i in [('en',1),('uz',2),('ru',3)]:
    def mixed(lang=lang,i=i):
     s72.State.users['s72-token-a']['ui_locale']='ar';state['latest']=i;visit(routes['compliance']);check(page.locator('html').get_attribute('dir')=='rtl' and page.locator('.compliance-narrative').get_attribute('dir')=='ltr','mixed direction');page.screenshot(path=str(OUT/f'compliance-ar-ui-{lang}-analysis.png'),full_page=True)
    case('compliance/arabic-ui/'+lang,mixed)
   s72.State.users['s72-token-a']['ui_locale']='en';state['latest']=3;page.set_viewport_size({'width':1024,'height':1000});visit(routes['compliance'])
   case('compliance/1024/bounds',lambda:check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'tablet overflow'))
   page.screenshot(path=str(OUT/'compliance-en-1024.png'),full_page=True)
   def override():
    page.set_viewport_size({'width':1440,'height':1000})
    prior=json.dumps(versions,sort_keys=True);page.get_by_role('button',name='Override system flag',exact=True).click();expect(page.locator('dialog[open]')).to_be_visible();page.get_by_label('Justification',exact=True).fill('Recorded company evidence requires this explicit decision.');page.screenshot(path=str(OUT/'compliance-override.png'),full_page=True);axe_check('compliance-override');page.get_by_role('button',name='Record override',exact=True).click();expect(page.locator('dialog[open]')).to_have_count(0);expect(page.locator('.compliance-requirement').first).to_contain_text('Overridden');check(prior==json.dumps(versions,sort_keys=True),'immutable version changed');check(writes[-1][2]['analysis_id']=='analysis-a','override authority')
   case('compliance/override-dialog-immutable-result',override)
   for name,path in routes.items():
    s72.State.users['s72-token-a']['ui_locale']='en';visit(path);page.locator('[data-customer-shell]').evaluate('(e)=>e.dataset.continuity="s104"')
    if name=='profile':page.get_by_label('Company name',exact=True).fill('Dirty locale-preserved name')
    if name=='readiness':
     with page.expect_response(lambda r:'/vault/readiness?' in r.url and 'available' in r.url):page.locator('.readiness-filters').get_by_label('Status',exact=True).select_option('available')
     expect(page.locator('.readiness-record')).to_have_count(8)
    if name=='compliance':page.get_by_role('combobox',name='Version history',exact=True).select_option('2');expect(page.locator('.compliance-narrative')).to_contain_text(s82.localized('uz')[1])
    for locale in ['ar','ru']:
     def continuity(locale=locale,name=name):
      original=page.url;start=len(requests);prior=snapshot();default=s72.State.users['s72-token-a']['default_analysis_language']
      page.evaluate("""async locale=>{const session=await(await fetch('/api/auth/session')).json();const r=await fetch('/api/v1/users/me/preferences',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+session.accessToken},body:JSON.stringify({ui_locale:locale})});if(!r.ok)throw new Error('preference failed');await fetch('/api/ui-locale',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ui_locale:locale})});const node=document.querySelector('[data-customer-shell]');let fiber=node[Object.keys(node).find(k=>k.startsWith('__reactFiber'))];while(fiber){const v=fiber.memoizedProps?.value;if(v&&typeof v.refresh==='function'&&typeof v.push==='function'){v.refresh();return;}fiber=fiber.return;}throw new Error('router unavailable');}""",locale)
      expect(page.locator('html')).to_have_attribute('lang',locale);expect(page.locator('[data-customer-shell]')).to_have_attribute('data-continuity','s104');check(original==page.url and prior==snapshot(),'locale domain or route mutation');check(default==s72.State.users['s72-token-a']['default_analysis_language'],'default language changed');check(not any(urlparse(p).path in ['/api/v1/users/me/company','/api/v1/vault/readiness','/api/v1/tenders/s72-tender/latest-analysis'] or '/versions/' in p for _,p in requests[start:]),'locale domain refetch')
      if name=='profile':expect(page.locator('#company-profile-form input').first).to_have_value('Dirty locale-preserved name')
      if name=='readiness':expect(page.locator('.readiness-filters select').nth(1)).to_have_value('available')
      if name=='compliance':expect(page.locator('.compliance-history select')).to_have_value('2');check(page.locator('.compliance-narrative').get_attribute('dir')=='ltr','analysis direction changed')
     case(f'continuity/{name}/en-to-{locale}',continuity)
   s72.State.users['s72-token-a']['ui_locale']='en';visit(routes['readiness'])
   def readiness_failure():
    state['fail_write']=True;prior=snapshot();page.get_by_role('button',name='Add record',exact=True).click();page.get_by_label('Document name',exact=True).fill('Rejected record');page.get_by_role('button',name='Save record',exact=True).click();expect(page.locator('dialog[open]').get_by_role('alert')).to_contain_text('could not be saved');check(snapshot()==prior,'failed readiness mutation');page.keyboard.press('Escape')
   case('readiness/failed-create-retains-draft',readiness_failure)
   def absent_file():
    record=page.locator('.readiness-record').filter(has_text='Construction License 1').first;expect(record).to_contain_text('Available');expect(record).to_contain_text('No file reference');check(record.get_by_role('link').count()==0,'file absence inflated')
   case('readiness/metadata-without-file-is-not-missing',absent_file)
   for name,path in [('foreign-readiness','/api/v1/vault/readiness/foreign-record'),('foreign-analysis','/api/v1/tenders/s72-tender/analyses/foreign-analysis/versions/1')]:
    def deny(path=path):
     result=page.evaluate("""async path=>{const s=await(await fetch('/api/auth/session')).json();return (await fetch(path,{headers:{Authorization:'Bearer '+s.accessToken}})).status;}""",path);check(result==404,'fixture foreign access')
    case('ownership-fixture/'+name,deny)
   def arabic_rejection():
    code=page.evaluate("""async()=>{const s=await(await fetch('/api/auth/session')).json();return (await fetch('/api/v1/tenders/s72-tender/analyze?analysis_language=ar',{method:'POST',headers:{Authorization:'Bearer '+s.accessToken}})).status;}""");check(code==422,'Arabic generation accepted')
   case('compliance/arabic-api-rejection-fixture',arabic_rejection)
   def anonymous():
    ac=browser.new_context();ap=ac.new_page();ap.goto(BASE+routes['profile'],wait_until='networkidle');check('/dashboard/settings' not in ap.url,'anonymous access');ac.close()
   case('auth/anonymous-denial',anonymous);case('network/no-external-requests',lambda:check(not external,str(external)));browser.close()
 finally:
  os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=15);server.shutdown();log.close()
  if os.environ.get('PLASMA_S104_VISUAL_ONLY')!='1':(OUT/'results.json').write_text(json.dumps(rows,indent=2))
 passed=sum(r['status']=='PASS' for r in rows);print(f'{passed}/{len(rows)} PASS')
 if passed!=len(rows):raise SystemExit(1)
if __name__=='__main__':main()
