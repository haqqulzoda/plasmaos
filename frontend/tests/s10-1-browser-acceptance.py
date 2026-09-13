#!/usr/bin/env python3
"""Deterministic production Chromium component/shell gate; fixtures never enter app/ in the repository.
Uses the same production React/Next components. The permanent browser gate separately
proves authenticated route, provider, API and request-budget behavior.
"""
import json, os, shutil, subprocess, time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[2]
FRONT=Path(os.environ.get('PLASMA_FRONTEND_TEST_ROOT','/tmp/plasma-s101-frontend'))
OUT=ROOT/'docs/audits/s10_1/browser'
BASE='http://localhost:3115'

def main():
 if FRONT.resolve()==(ROOT/'frontend').resolve(): raise RuntimeError('Use an isolated Linux test copy, never repository app/')
 OUT.mkdir(parents=True,exist_ok=True)
 saved_config=(FRONT/'tsconfig.json').read_bytes(); saved_next_env=(FRONT/'next-env.d.ts').read_bytes()
 target=FRONT/'app/s101-fixture'; target.mkdir(parents=True,exist_ok=True)
 shutil.copy2(ROOT/'frontend/tests/fixtures/s10-1/page.tsx',target/'page.tsx')
 env={**os.environ,'AUTH_SECRET':'s101-synthetic-only','AUTH_URL':BASE,'NEXTAUTH_URL':BASE,'AUTH_TRUST_HOST':'true','NEXT_DIST_DIR':'.next-s101-fixture','BACKEND_INTERNAL_URL':'http://127.0.0.1:8115/api/v1'}
 try:
  with (OUT/'build.log').open('w') as log: subprocess.run(['npm','run','build'],cwd=FRONT,env=env,stdout=log,stderr=log,check=True)
 finally:
  shutil.rmtree(target)
  (FRONT/'tsconfig.json').write_bytes(saved_config)
  (FRONT/'next-env.d.ts').write_bytes(saved_next_env)
 log=(OUT/'server.log').open('w'); proc=subprocess.Popen(['npm','run','start','--','-p','3115'],cwd=FRONT,env=env,stdout=log,stderr=log,start_new_session=True)
 rows=[]; errors=[]; external=[]
 def case(name,fn):
  try: value=fn(); rows.append({'case':name,'status':'PASS','evidence':value})
  except Exception as e: rows.append({'case':name,'status':'FAIL','error':str(e)[:1500]})
  print(rows[-1]['status'],name,flush=True)
 def check(condition,message):
  if not condition: raise AssertionError(message)
 try:
  for _ in range(60):
   try: urlopen(BASE+'/s101-fixture',timeout=2);break
   except Exception: time.sleep(1)
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
   context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
   def route(r):
    if r.request.url.startswith(('http://localhost:3115/','http://127.0.0.1:3115/')): r.continue_()
    else: external.append(r.request.url);r.abort()
   context.route('**/*',route);page=context.new_page();page.set_default_timeout(6000);page.on('pageerror',lambda e:errors.append(str(e)))
   labels={loc:json.loads((ROOT/f'frontend/messages/{loc}/navigation.json').read_text()) for loc in ['en','uz','ru','ar']}
   for admin in [False,True]:
    for locale in (['en','ar'] if admin else ['en','uz','ru','ar']):
     for width in [320,390,768,1440]:
      prefix=f'{"admin" if admin else "customer"}/{locale}/{width}'
      page.set_viewport_size({'width':width,'height':1000}); page.goto(f'{BASE}/s101-fixture?locale={locale}&admin={int(admin)}',wait_until='networkidle')
      shell=page.locator('.app-shell'); expected_dir='ltr' if admin or locale!='ar' else 'rtl'
      case(prefix+'/direction',lambda:check(shell.evaluate('(e)=>getComputedStyle(e).direction')==expected_dir,'wrong shell direction'))
      case(prefix+'/overflow',lambda:check(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'page overflow'))
      case(prefix+'/brand',lambda:check(page.locator('.plasma-mark:visible').first.evaluate('(e)=>e.complete && e.naturalWidth>0'),'logo not loaded'))
      case(prefix+'/typography',lambda:check('sans-serif' in shell.evaluate('(e)=>getComputedStyle(e).fontFamily'),'not sans serif'))
      if width<1024:
       open_label='Open navigation' if admin else labels[locale]['openNavigation'];close_label='Close navigation' if admin else labels[locale]['closeNavigation']
       def drawer_case():
        page.get_by_role('button',name=open_label,exact=True).click(); d=page.locator('dialog[open]');expect(d).to_be_visible();check(d.evaluate('(e)=>e.contains(document.activeElement)'),'focus not in navigation');check(page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'drawer overflow');page.screenshot(path=str(OUT/f'{prefix.replace("/","-")}-navigation.png'));page.keyboard.press('Escape');expect(d).to_have_count(0);expect(page.get_by_role('button',name=open_label,exact=True)).to_be_focused()
       case(prefix+'/mobile-navigation-focus-escape',drawer_case)
      else:
       case(prefix+'/desktop-navigation',lambda:expect(page.locator('.shell-sidebar nav')).to_be_visible())
      def account_case():
       label='Account menu' if admin else labels[locale]['accountMenu'];page.get_by_role('button',name=label,exact=True).click();expect(page.get_by_role('menu',name=label)).to_be_visible();page.keyboard.press('ArrowDown');check(page.get_by_role('menu').evaluate('(e)=>e.contains(document.activeElement)'),'menu focus');page.keyboard.press('Escape');expect(page.get_by_role('menu')).to_have_count(0)
      case(prefix+'/account-keyboard',account_case)
      case(prefix+'/console',lambda:check(not errors,str(errors)))
      page.screenshot(path=str(OUT/f'{prefix.replace("/","-")}.png'))
   page.goto(BASE+'/s101-fixture',wait_until='networkidle')
   case('form/label-association',lambda:expect(page.get_by_label('Company name',exact=True)).to_be_editable())
   case('form/error-association',lambda:check(page.get_by_label('Invalid field').evaluate('(e)=>e.getAttribute("aria-invalid")==="true" && document.getElementById(e.getAttribute("aria-describedby")).textContent.includes("required")'),'missing error association'))
   case('form/disabled',lambda:expect(page.get_by_label('Disabled field')).to_be_disabled())
   case('form/read-only',lambda:check(page.get_by_label('Email',exact=True).get_attribute('readonly') is not None,'not read only'))
   def search():
    page.get_by_role('searchbox',name='Search',exact=True).fill('query');page.get_by_role('button',name='Clear search').click();expect(page.get_by_role('searchbox')).to_have_value('')
   case('search/controlled-clear',search)
   def select():
    page.get_by_label('Status',exact=True).select_option(label='Active');expect(page.get_by_label('Status',exact=True)).to_have_value('Active')
   case('select/native-selection',select)
   def checkbox():
    c=page.get_by_label('Include archived');c.focus();page.keyboard.press('Space');expect(c).to_be_checked()
   case('checkbox/keyboard',checkbox)
   def radio():
    page.get_by_label('First mode').focus();page.keyboard.press('ArrowDown');expect(page.get_by_label('Second mode')).to_be_checked()
   case('radio/keyboard',radio)
   def segments():
    page.get_by_role('radio',name='All',exact=True).focus();page.keyboard.press('ArrowRight');expect(page.get_by_role('radio',name='Recommended',exact=True)).to_be_checked()
   case('segments/native-keyboard',segments)
   def tabs():
    page.get_by_role('tab',name='First tab').focus();page.keyboard.press('ArrowRight');expect(page.get_by_role('tab',name='Second tab')).to_have_attribute('aria-selected','true');expect(page.get_by_role('tabpanel')).to_have_text('Second panel');page.keyboard.press('ArrowRight');expect(page.get_by_role('tab',name='First tab')).to_be_focused()
   case('tabs/arrow-navigation-disabled-skip',tabs)
   case('buttons/loading-disabled',lambda:expect(page.get_by_role('button',name='Saving',exact=True)).to_be_disabled())
   case('buttons/loading-announced',lambda:expect(page.get_by_role('button',name='Saving',exact=True)).to_have_attribute('aria-busy','true'))
   def overlay(kind):
    trigger=page.get_by_role('button',name='Open '+kind,exact=True);trigger.click();d=page.locator('dialog[open]');expect(d).to_be_visible();check(d.evaluate('(e)=>e.contains(document.activeElement)'),'initial focus');
    for _ in range(8):page.keyboard.press('Tab');check(d.evaluate('(e)=>e.contains(document.activeElement)'),'focus escaped modal')
    page.keyboard.press('Escape');expect(d).to_have_count(0);expect(trigger).to_be_focused()
   case('dialog/focus-trap-escape-restore',lambda:overlay('dialog'))
   case('drawer/focus-trap-escape-restore',lambda:overlay('drawer'))
   def tooltip():
    page.get_by_role('button',name='Tooltip control').focus();expect(page.get_by_role('tooltip')).to_be_visible();page.keyboard.press('Escape');expect(page.get_by_role('tooltip')).to_have_count(0)
   case('tooltip/focus-escape',tooltip)
   def alert():page.get_by_role('button',name='Dismiss alert').click();expect(page.get_by_text('Review required',exact=True)).to_have_count(0)
   case('alert/dismiss',alert)
   case('table/semantics',lambda:expect(page.get_by_role('table')).to_have_count(1))
   case('table/numeric-alignment',lambda:check(page.locator('td.ds-numeric').evaluate('(e)=>getComputedStyle(e).textAlign')=='end','numeric alignment'))
   case('motion/reduced',lambda:check(page.locator('.ds-skeleton').first.evaluate('(e)=>getComputedStyle(e).animationName')=='none','animation active'))
   case('bidi/technical-isolation',lambda:check(page.locator('bdi.technical-ltr').last.evaluate('(e)=>getComputedStyle(e).direction')=='ltr','technical content not LTR'))
   case('shell/no-notification-route',lambda:expect(page.locator('a[href*="notification"],a[href*="broadcast"]')).to_have_count(0))
   case('fixture/no-external-network',lambda:check(not external,str(external)))
   axe=Path(os.environ.get('PLASMA_AXE_PATH','/tmp/plasma-s101-qa/node_modules/axe-core/axe.min.js'))
   if axe.exists():
    for admin in [0,1]:
     page.goto(f'{BASE}/s101-fixture?admin={admin}',wait_until='networkidle');page.add_script_tag(path=str(axe));result=page.evaluate('async()=>await axe.run(document,{runOnly:{type:"tag",values:["wcag2a","wcag2aa","wcag21aa"]}})');(OUT/f'axe-{admin}.json').write_text(json.dumps(result,indent=2));serious=[v for v in result['violations'] if v['impact'] in ['serious','critical']];case(f'axe/{admin}/serious-critical',lambda:check(not serious,str([(v['id'],len(v['nodes'])) for v in serious])))
   else:rows.append({'case':'axe/tooling','status':'BLOCKED','error':'axe-core not installed'})
   browser.close()
 finally:
  import signal
  os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=15);log.close()
  (OUT/'results.json').write_text(json.dumps(rows,indent=2))
 passed=sum(r['status']=='PASS' for r in rows);print(f'{passed}/{len(rows)} PASS',flush=True)
 if passed<60 or passed!=len(rows):raise SystemExit(1)
if __name__=='__main__':main()
