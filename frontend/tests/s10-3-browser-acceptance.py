#!/usr/bin/env python3
"""Sprint 10.3 production Chromium: local fixtures only; no production identity/data.
Run sequentially with the maintained browser gate (shared 3114/8114 ports).
Backend ownership/DB fingerprints are independently verified by the release gate.
"""
import importlib.util,json,os,signal,subprocess,threading,time,copy
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from urllib.request import urlopen
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[2];FRONT=Path(os.environ.get('PLASMA_FRONTEND_TEST_ROOT','/tmp/plasma-s102-final'));OUT=ROOT/'docs/audits/s10_3/browser';BASE='http://localhost:3114'
def load(name,file):
 spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(file));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 fixture=load('s103_rtl','s8-3-arabic-rtl-browser-acceptance.py');my=load('s103_my','my-tenders-browser-acceptance.py');bid=load('s103_bid','bid-preparation-browser-acceptance.py');s72=fixture.s72
 s72.State.active=False;s72.State.users['s72-token-a'].update(ui_locale='en',default_analysis_language='uz')
 statuses=['SAVED','EVALUATING','PREPARING','SUBMITTED','WON','LOST','DISMISSED'];titles=['Digital public administration services','Sustainable energy technical assistance','Regional transport modernization','Healthcare equipment installation','Water treatment facility design','Public sector training services','Procurement advisory services']
 tenders=[my.tender(f's103-tender-{i}',titles[i],source='world_bank',status='CLOSED' if i in [3,4,5] else 'OPEN') for i in range(7)]
 entries=[my.engagement(t,statuses[i],project=True) for i,t in enumerate(tenders)]
 proposals=[{**bid.proposal(f's103-proposal-{i}',tenders[i],status=status),'engagement_status':statuses[i],'ai_confidence_score':[72,68,55,80][i],'structured_data':{'our_price':[0,4200000,100000,1950000][i],'strategic_summary':'Original user content — النص الأصلي'}} for i,status in enumerate(['GENERATING','DRAFT','COMPLETED','SUBMITTED'])]
 state={'mode':'populated','reject':False,'delay':False};requests=[];external=[];errors=[];rows=[]
 def public(row):return {k:v for k,v in row.items() if k!='owner'}
 class Handler(fixture.Handler):
  def do_GET(self):
   parsed=urlparse(self.path);path=parsed.path;q=parse_qs(parsed.query);requests.append(('GET',self.path))
   if path in ['/api/v1/my-tenders','/api/v1/proposals']:
    if state['delay']:time.sleep(1)
    if state['mode'] in ['failure','denied']:return self.send_json(403 if state['mode']=='denied' else 503,{'detail':'fixture unavailable'})
   if path=='/api/v1/my-tenders':
    allrows=copy.deepcopy(entries) if state['mode']!='empty' else []
    if state['mode']=='pagination':allrows=[{**entries[i%7],'engagement_id':f'page-engagement-{i}'} for i in range(60)]
    counts={s.lower():sum(x['engagement_status']==s for x in allrows) for s in statuses};counts.update(all=len(allrows),active=len(allrows)-counts['dismissed'])
    view=q.get('status',['ACTIVE'])[0]
    if view not in ['ACTIVE','ALL']+statuses:return self.send_json(422,{'detail':'invalid status'})
    items=[x for x in allrows if view=='ALL' or (view=='ACTIVE' and x['engagement_status']!='DISMISSED') or x['engagement_status']==view]
    for param,field in [('source','source_system'),('tender_status','tender_status')]:
     if q.get(param):items=[x for x in items if x[field]==q[param][0]]
    if q.get('search'):items=[x for x in items if q['search'][0].lower() in (x['tender_title']+' '+x['buyer']).lower()]
    offset=int(q.get('offset',['0'])[0]);return self.send_json(200,{'items':[public(x) for x in items[offset:offset+25]],'total':len(items),'offset':offset,'limit':25,'counts':counts})
   if path=='/api/v1/proposals':
    items=proposals if state['mode']!='empty' else []
    if state['mode']=='pagination':items=[{**proposals[i%4],'id':f'page-proposal-{i}'} for i in range(31)]
    offset=int(q.get('offset',['0'])[0]);body=json.dumps([public(x) for x in items[offset:offset+25]]).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('X-Total-Count',str(len(items)));self.send_header('X-Has-More',str(offset+25<len(items)).lower());self.end_headers();self.wfile.write(body);return
   if path.startswith('/api/v1/proposals/'):
    row=next((x for x in proposals if x['id']==path.rsplit('/',1)[1]),None);return self.send_json(200 if row else 404,public(row) if row else {'detail':'not found'})
   if path.startswith('/api/v1/my-tenders/'):return self.send_json(404,{'detail':'not found'})
   if path.startswith('/api/v1/tenders/s103-tender-'):
    if path.endswith('/documents'):return self.send_json(200,[])
    row=next((x for x in tenders if x['id']==path.rsplit('/',1)[1]),None)
    if row:return self.send_json(200,row)
   return super().do_GET()
  def do_POST(self):
   path=urlparse(self.path).path;requests.append(('POST',self.path))
   if path.startswith('/api/v1/my-tenders/'):
    parts=path.split('/');row=next((x for x in entries if x['engagement_id']==parts[4]),None);body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or '{}')
    if not row:return self.send_json(404,{'detail':'not found'})
    if state['reject'] or body.get('expected_status')!=row['engagement_status']:return self.send_json(409,{'detail':'state changed'})
    target={'evaluate':'EVALUATING','mark-submitted':'SUBMITTED','mark-won':'WON','mark-lost':'LOST','dismiss':'DISMISSED','correct-to-preparing':'PREPARING','correct-to-submitted':'SUBMITTED','correct-to-won':'WON','correct-to-lost':'LOST'}[parts[-1]]
    idx=entries.index(row);entries[idx]=my.engagement(tenders[idx],target,project=True);return self.send_json(200,{'engagement':public(entries[idx])})
   if path=='/api/v1/proposals/prepare':
    body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or '{}');idx=next(i for i,x in enumerate(tenders) if x['id']==body['tender_id']);entries[idx]=my.engagement(tenders[idx],'PREPARING',project=True)
    return self.send_json(200,{'proposal':public(proposals[idx]),'engagement':public(entries[idx]),'proposal_created':False,'engagement_created':False})
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
   c.route('**/*',network);page=c.new_page();page.set_default_timeout(15000);page.set_default_navigation_timeout(30000);expect.set_options(timeout=15000);page.on('pageerror',lambda e:errors.append(str(e)))
   routes={'my-tenders':'/dashboard/my-tenders','bid-preparation':'/dashboard/bid-preparation'}
   def visit(path):return page.goto(BASE+path,wait_until='networkidle')
   for locale in ['en','uz','ru','ar']:
    s72.State.users['s72-token-a']['ui_locale']=locale
    for width in [320,390,768,1440]:
     page.set_viewport_size({'width':width,'height':1000})
     for name,path in routes.items():
      start=len(requests);errors.clear();before=json.dumps([entries,proposals]);response=visit(path);expect(page.locator('h1')).to_be_visible();prefix=f'{name}/{locale}/{width}'
      case(prefix+'/render',lambda:check(response.status==200 and not errors,str(errors)))
      case(prefix+'/direction',lambda:check(page.locator('html').get_attribute('lang')==locale and page.locator('.customer-page').evaluate('(e)=>getComputedStyle(e).direction')==('rtl' if locale=='ar' else 'ltr'),'locale/direction'))
      case(prefix+'/bounds',lambda:check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+1') and page.locator('.customer-page').evaluate('(e)=>[...e.querySelectorAll("button,select,input")].filter(x=>x.checkVisibility()).every(x=>{const r=x.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1;})'),'overflow/control bounds'))
      case(prefix+'/foundation',lambda:check(page.locator('.shell-legacy-content').count()==0 and page.locator('.ds-surface').count()>0,'legacy wrapper'))
      def passive():
       calls=requests[start:];counts=Counter(urlparse(p).path for _,p in calls);check(all(m=='GET' or p.startswith('/api/v1/auth/refresh') for m,p in calls),'passive write');check(len(calls)<=30 and counts['/api/v1/users/me']<=8 and counts['/api/v1/auth/refresh']<=6,'request budget '+str(counts));check(counts['/api/v1/my-tenders']+counts['/api/v1/proposals']==1,'duplicate list read');check(not any('/details' in p or '/latest-analysis' in p or '/documents' in p for _,p in calls),'N+1 read');check(before==json.dumps([entries,proposals]),'fixture domain changed');return dict(counts)
      case(prefix+'/passivity-budget',passive);page.screenshot(path=str(OUT/f'{name}-{locale}-{width}.png'),full_page=True)
      if locale in ['en','ar'] and width in [390,1440]:
       def axe_check(prefix=prefix):
        page.add_script_tag(path=os.environ.get('PLASMA_AXE_PATH','/tmp/plasma-s101-qa/node_modules/axe-core/axe.min.js'));result=page.evaluate('async()=>await axe.run(document,{runOnly:{type:"tag",values:["wcag2a","wcag2aa","wcag21aa"]}})');(OUT/(prefix.replace('/','-')+'-axe.json')).write_text(json.dumps(result));bad=[v for v in result['violations'] if v['impact'] in ['serious','critical']];check(not bad,str([(v['id'],len(v['nodes'])) for v in bad]));return {'serious_critical':len(bad)}
       case(prefix+'/axe',axe_check)
   s72.State.users['s72-token-a']['ui_locale']='en';page.set_viewport_size({'width':1440,'height':1000})
   for status in ['ACTIVE','ALL']+statuses:
    def status_case(status=status):
     visit('/dashboard/my-tenders?status='+status);expected=sum(status=='ALL' or (status=='ACTIVE' and x['engagement_status']!='DISMISSED') or x['engagement_status']==status for x in entries);check(page.locator('[data-engagement-id]').count()==expected,'incorrect membership');expect(page.get_by_role('tab',selected=True)).to_contain_text('Active' if status=='ACTIVE' else status.title());check(page.locator('[role=tablist]').inner_text().count('7')>=1,'backend total missing')
    case('pursuit/status/'+status,status_case)
   for query in ['source=world_bank','tender_status=CLOSED','search=energy','sort=recently_added','sort=deadline_soonest']:
    def query_case(query=query):
     start=len(requests);visit('/dashboard/my-tenders?'+query);actual=parse_qs(urlparse(next(p for m,p in requests[start:] if p.startswith('/api/v1/my-tenders?'))).query);expected=parse_qs(query);check(all(actual.get(k)==v for k,v in expected.items()),str(actual))
    case('pursuit/query/'+query,query_case)
   for name,path in routes.items():
    for mode in ['empty','failure','denied']:
     def states(name=name,path=path,mode=mode):
      state['mode']=mode;visit(path);expect(page.locator('.customer-page').get_by_role('alert')).to_be_visible() if mode!='empty' else expect(page.locator('.customer-page')).to_contain_text('No tenders saved yet' if name=='my-tenders' else 'No bid preparations yet');page.screenshot(path=str(OUT/f'{name}-{mode}.png'),full_page=True)
      if mode=='failure':state['mode']='populated';page.get_by_role('button',name='Try again',exact=True).click();expect(page.locator('[role=article]').first).to_be_visible()
     case(name+'/state/'+mode,states)
    state['mode']='pagination'
    def pagination(path=path,name=name):
     visit(path);expect(page.locator('[role=article]')).to_have_count(25);page.get_by_role('button',name='Next',exact=True).click();page.wait_for_url('**page=2');expect(page.get_by_role('button',name='Previous',exact=True)).to_be_enabled();check(page.locator('[role=article]').count()<=25,'row bound');page.get_by_role('button',name='Previous',exact=True).click();page.wait_for_url(lambda u:'page=2' not in u)
    case(name+'/pagination',pagination);state['mode']='populated'
    def loading(path=path):
     state['delay']=True;page.goto(BASE+path,wait_until='domcontentloaded');expect(page.locator('.customer-page [role=status]').first).to_be_visible();page.wait_for_load_state('networkidle');state['delay']=False
    case(name+'/loading',loading)
   def invalid_filter():
    visit('/dashboard/my-tenders?status=INVALID');expect(page.locator('.customer-page').get_by_role('alert')).to_be_visible()
   case('pursuit/invalid-filter-recovery',invalid_filter)
   for width in [320,390,768]:
    for locale in ['en','ar']:
     def mobile_menu(width=width,locale=locale):
      s72.State.users['s72-token-a']['ui_locale']=locale;page.set_viewport_size({'width':width,'height':1000});visit('/dashboard/my-tenders');row=page.locator('[data-engagement-id]').first;button=row.locator('button[aria-haspopup="menu"]');button.click();menu=row.get_by_role('menu');expect(menu).to_be_visible();check(menu.evaluate('(e)=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;}'),'mobile menu overflow');page.add_script_tag(path=os.environ.get('PLASMA_AXE_PATH','/tmp/plasma-s101-qa/node_modules/axe-core/axe.min.js'));result=page.evaluate('async()=>await axe.run(document,{runOnly:{type:"tag",values:["wcag2a","wcag2aa","wcag21aa"]}})');bad=[v for v in result['violations'] if v['impact'] in ['serious','critical']];check(not bad,str([(v['id'],len(v['nodes'])) for v in bad]));page.screenshot(path=str(OUT/f'menu-{locale}-{width}.png'));page.keyboard.press('Escape');expect(button).to_be_focused()
     case(f'pursuit/mobile-menu/{locale}/{width}',mobile_menu)
   s72.State.users['s72-token-a']['ui_locale']='en';page.set_viewport_size({'width':1440,'height':1000})
   def filtered_empty():visit('/dashboard/my-tenders?search=no-such-record');expect(page.locator('.customer-page')).to_contain_text('No matching tenders')
   case('pursuit/filtered-empty',filtered_empty)
   def search():
    visit('/dashboard/my-tenders');page.get_by_role('searchbox').fill('energy');page.get_by_role('button',name='Search',exact=True).click();page.wait_for_url('**search=energy**');expect(page.locator('[data-engagement-id]')).to_have_count(1);page.get_by_role('button',name='Clear search',exact=True).click();page.wait_for_url(lambda u:'search=' not in u);expect(page.get_by_role('searchbox')).to_be_focused()
   case('pursuit/search-clear',search)
   def keyboard_tabs():
    visit('/dashboard/my-tenders');page.get_by_role('tab',selected=True).focus();page.keyboard.press('ArrowRight');page.wait_for_url('**status=ALL**');expect(page.get_by_role('tab',selected=True)).to_be_focused()
   case('pursuit/keyboard-tabs',keyboard_tabs)
   for idx,status in enumerate(statuses):
    def menu_case(idx=idx,status=status):
     visit('/dashboard/my-tenders?status=ALL');row=page.locator(f'[data-engagement-id="{entries[idx]["engagement_id"]}"]');button=row.get_by_role('button',name='More actions',exact=True);button.click();menu=row.get_by_role('menu');expect(menu).to_be_visible();check(menu.locator('[role=menuitem]').count()>=len(entries[idx]['allowed_actions']),'missing allowed action');check(menu.evaluate('(e)=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;}'),'menu bounds');page.keyboard.press('Escape');expect(button).to_be_focused()
    case('pursuit/allowed-menu/'+status,menu_case)
   transitions=[(0,'Evaluate','EVALUATING',False),(2,'Mark as Submitted','SUBMITTED',True),(3,'Record as Won','WON',True),(4,'Correct outcome to Lost','LOST',True),(5,'Correct outcome to Won','WON',True),(1,'Dismiss','DISMISSED',False)]
   for idx,label,target,confirm in transitions:
    def transition(idx=idx,label=label,target=target,confirm=confirm):
     visit('/dashboard/my-tenders?status=ALL');row=page.locator(f'[data-engagement-id="{entries[idx]["engagement_id"]}"]');row.get_by_role('button',name='More actions',exact=True).click();row.get_by_role('menuitem',name=label,exact=True).click()
     if confirm:expect(page.locator('dialog[open]')).to_be_visible();page.locator('dialog[open]').get_by_role('button',name=label,exact=True).click()
     expect(row).to_contain_text('Engagement: '+target.title());check(entries[idx]['engagement_status']==target,'transition rejected');expect(row.get_by_role('button',name='More actions',exact=True)).to_be_focused()
    case('pursuit/transition/'+label,transition)
   def rejected():
    state['reject']=True;visit('/dashboard/my-tenders?status=ALL');row=page.locator(f'[data-engagement-id="{entries[2]["engagement_id"]}"]');row.get_by_role('button',name='More actions',exact=True).click();row.get_by_role('menuitem',name='Record as Lost',exact=True).click();page.locator('dialog[open]').get_by_role('button',name='Record as Lost',exact=True).click();expect(row.get_by_role('alert')).to_contain_text('Status changed');check(entries[2]['engagement_status']=='SUBMITTED','optimistic state');state['reject']=False
   case('pursuit/rejected-transition',rejected)
   def proposal_boundaries():
    visit('/dashboard/bid-preparation');expect(page.locator('[data-proposal-id]')).to_have_count(4);expect(page.locator('[data-proposal-id="s103-proposal-3"]')).to_contain_text('Preparation: Submitted');expect(page.locator('[data-proposal-id="s103-proposal-3"]')).to_contain_text('Tender: Closed');expect(page.locator('[data-proposal-id="s103-proposal-0"]')).to_contain_text('72%');check(page.get_by_role('searchbox').count()==0,'unsupported search');check(not page.locator('.customer-page').get_by_text('active bids',exact=False).count(),'false active count')
   case('proposal/status-price-confidence-boundaries',proposal_boundaries)
   def open_proposal():
    visit('/dashboard/bid-preparation');start=len(requests);page.locator('[data-proposal-id="s103-proposal-1"]').get_by_role('link',name='Continue Bid Preparation',exact=True).click();page.wait_for_url('**/bid-preparation/s103-proposal-1');page.wait_for_load_state('networkidle');check(not any(m=='POST' and '/auth/' not in p for m,p in requests[start:]),'implicit preparation')
   case('proposal/open-owned-artifact-passive',open_proposal)
   def handoff():
    visit('/dashboard/my-tenders?status=ALL');row=page.locator(f'[data-engagement-id="{entries[0]["engagement_id"]}"]');row.get_by_role('button',name='More actions',exact=True).click();row.get_by_role('menuitem',name='Prepare Bid',exact=True).click();page.wait_for_url('**/bid-preparation/s103-proposal-0');check(entries[0]['engagement_status']=='PREPARING','canonical prepare side effect missing')
   case('pursuit/explicit-preparation-handoff',handoff)
   for name,path in routes.items():
    def tender_link(name=name,path=path):
     visit(path);link=page.locator('.customer-page').get_by_role('link',name='Open Tender',exact=True).first;check(link.get_attribute('href').startswith('/dashboard/tenders/s103-tender-'),'wrong domain id')
    case(name+'/tender-link',tender_link)
    def owner_denial(name=name,path=path):
     visit(path);start=json.dumps([entries,proposals]);result=page.evaluate("""async name=>{const session=await(await fetch('/api/auth/session')).json();const base='/api/v1/'+(name==='my-tenders'?'my-tenders/foreign-engagement':'proposals/foreign-proposal');return await Promise.all(['GET','POST'].map(async method=>{const r=await fetch(base+(method==='POST'&&name==='my-tenders'?'/actions/dismiss':''),{method,headers:{Authorization:'Bearer '+session.accessToken}});return r.status;}));}""",name);check(all(code in [403,404,405] for code in result),str(result));check(start==json.dumps([entries,proposals]),'foreign record mutation')
    case(name+'/tenant-owned-ui-and-api-denial',owner_denial)
   # Test-only access to mounted AppRouter; mirrors production preference/cookie/refresh sequence.
   for name,path in routes.items():
    s72.State.active=True;s72.State.users['s72-token-a']['ui_locale']='en';state['mode']='pagination';visit(path+'?page=2'+('&status=ALL&source=world_bank' if name=='my-tenders' else ''));page.locator('[data-customer-shell]').evaluate('(e)=>e.dataset.continuity="s103"')
    for locale in ['ar','ru']:
     def locale_change(locale=locale,name=name):
      original=page.url;start=len(requests);ids=page.locator('[role=article]').evaluate_all('(xs)=>xs.map(x=>x.dataset.engagementId||x.dataset.proposalId)')
      page.evaluate("""async locale=>{const session=await(await fetch('/api/auth/session')).json();const r=await fetch('/api/v1/users/me/preferences',{method:'PATCH',headers:{'Content-Type':'application/json',Authorization:'Bearer '+session.accessToken},body:JSON.stringify({ui_locale:locale})});if(!r.ok)throw new Error('preference failed');await fetch('/api/ui-locale',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ui_locale:locale})});const node=document.querySelector('[data-customer-shell]');let fiber=node[Object.keys(node).find(k=>k.startsWith('__reactFiber'))];while(fiber){const v=fiber.memoizedProps?.value;if(v&&typeof v.refresh==='function'&&typeof v.push==='function'){v.refresh();return;}fiber=fiber.return;}throw new Error('router unavailable');}""",locale)
      expect(page.locator('html')).to_have_attribute('lang',locale);expect(page.locator('[data-customer-shell]')).to_have_attribute('data-continuity','s103');check(page.url==original,'URL lost');check(ids==page.locator('[role=article]').evaluate_all('(xs)=>xs.map(x=>x.dataset.engagementId||x.dataset.proposalId)'),'records lost');check(not any(urlparse(p).path in ['/api/v1/my-tenders','/api/v1/proposals'] for _,p in requests[start:]),'locale data refetch');check(s72.State.max_activity_in_flight<=1,'duplicate refresh poller');check(s72.State.users['s72-token-a']['default_analysis_language']=='uz','analysis language changed')
     case(f'continuity/{name}/en-to-{locale}',locale_change)
   state['mode']='populated';s72.State.active=False
   def anonymous():
    ac=browser.new_context();ap=ac.new_page();ap.goto(BASE+'/dashboard/my-tenders',wait_until='networkidle');check('/dashboard/my-tenders' not in ap.url,'anonymous access');ac.close()
   case('auth/anonymous-denial',anonymous);case('network/no-external-requests',lambda:check(not external,str(external)));browser.close()
 finally:
  os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=15);server.shutdown();log.close();(OUT/'results.json').write_text(json.dumps(rows,indent=2))
 passed=sum(r['status']=='PASS' for r in rows);print(f'{passed}/{len(rows)} PASS')
 if passed!=len(rows):raise SystemExit(1)
if __name__=='__main__':main()
