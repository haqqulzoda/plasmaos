#!/usr/bin/env python3
"""Portable production-build Chromium gate: local fixtures and real backend guards.

Requires a build with BACKEND_INTERNAL_URL=http://127.0.0.1:8114/api/v1 and
NEXT_DIST_DIR=.next-release-test. No Windows browser paths or external services.
"""
import asyncio
from collections import Counter
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
from unittest.mock import AsyncMock, patch

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
FRONT = Path(os.environ.get("PLASMA_FRONTEND_TEST_ROOT", str(ROOT / "frontend")))
OUT = Path(os.environ.get("PLASMA_BROWSER_RESULTS", str(ROOT / "docs/audits/s9_3/browser")))
BASE = "http://localhost:3114"


def load_fixture():
    spec = importlib.util.spec_from_file_location("release_ui_fixture", Path(__file__).with_name("s8-3-arabic-rtl-browser-acceptance.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fixture = load_fixture()
    s72 = fixture.s72
    s72.State.active = False
    requests = []
    controls = {"outage": False, "pagination": False, "revoked": False}
    rows = []

    class Handler(fixture.Handler):
        def send_json(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            offset = int(parse_qs(urlparse(self.path).query).get("offset", ["0"])[0])
            self.send_header("X-Has-More", str(controls["pagination"] and offset == 0).lower())
            self.send_header("X-Total-Count", "26" if controls["pagination"] else "1")
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            requests.append(("GET", self.path))
            if controls["revoked"] and urlparse(self.path).path.startswith("/api/v1/"):
                return self.send_json(401, {"detail":"Session revoked"})
            if urlparse(self.path).path == "/api/v1/tenders/documents/missing-fixture/download":
                return self.send_json(404, {"detail":"Document file is not stored"})
            if controls["outage"] and urlparse(self.path).path in {"/api/v1/users/me", "/api/v1/users/me/access-status"}:
                return self.send_json(503, {"detail": "Controlled temporary outage"})
            return super().do_GET()
        def do_POST(self):
            requests.append(("POST", self.path))
            return super().do_POST()
        def do_PATCH(self):
            requests.append(("PATCH", self.path))
            return super().do_PATCH()

    server = ThreadingHTTPServer(("127.0.0.1", 8114), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = os.environ.copy()
    env.update(AUTH_SECRET="s72-browser-secret", AUTH_URL=BASE, NEXTAUTH_URL=BASE,
        AUTH_TRUST_HOST="true", NODE_ENV="production", NEXT_DIST_DIR=".next-release-test",
        BACKEND_INTERNAL_URL="http://127.0.0.1:8114/api/v1")
    log = (OUT / "frontend.log").open("w")
    proc = subprocess.Popen(["npm", "run", "start", "--", "-p", "3114"], cwd=FRONT, env=env, stdout=log, stderr=log, start_new_session=os.name == "posix")
    api_server = None
    external = []

    def case(name, action):
        selected = os.environ.get("PLASMA_BROWSER_CASE_FILTER")
        if selected and selected not in name:
            return
        try:
            evidence = action()
            rows.append({"case": name, "status": "PASS", "evidence": evidence})
        except Exception as error:
            rows.append({"case": name, "status": "FAIL", "error": str(error)[:2000]})
        print(rows[-1]["status"], name, flush=True)

    try:
        for _ in range(90):
            try:
                urlopen(BASE, timeout=2)
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("Local production frontend did not start")
        token_js = """import {encode} from 'next-auth/jwt'; console.log(await encode({secret:'s72-browser-secret',salt:'__Secure-authjs.session-token',token:{name:'Synthetic Pilot',email:'pilot@example.invalid',sub:'72000000-0000-4000-8000-000000000001',accessToken:process.env.TEST_ACCESS_TOKEN||'s72-token-a',approval_status:'approved',platform_role:'pilot_user'},maxAge:3600}));"""
        token = subprocess.check_output(["node", "--input-type=module", "-e", token_js], cwd=FRONT, env=env, text=True).strip()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(viewport={"width":390,"height":844})
            context.add_cookies([{"name":"__Secure-authjs.session-token","value":token,"domain":"localhost","path":"/","secure":True}])
            def network(route):
                if urlparse(route.request.url).hostname not in {"localhost", "127.0.0.1"}:
                    external.append(route.request.url.split("?")[0])
                    route.abort()
                else:
                    route.continue_()
            context.route("**/*", network)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            surfaces = [("explorer","tenders?view=all"),("my-tenders","my-tenders"),("bid-preparation","bid-preparation")]
            def load(path, locale, width):
                controls["outage"] = False
                s72.State.users["s72-token-a"]["ui_locale"] = locale
                page.set_viewport_size({"width":width,"height":900})
                errors.clear()
                before = len(requests)
                start_external = len(external)
                response = page.goto(BASE + "/dashboard/" + path, wait_until="networkidle")
                expect(page.locator('h1').first).to_be_visible(timeout=15000)
                page.wait_for_load_state('networkidle')
                page.wait_for_timeout(200)
                assert response.status == 200 and "/dashboard/" in page.url
                dom = page.evaluate("""() => ({lang:document.documentElement.lang, dir:document.documentElement.dir,
                    width:innerWidth, scroll:document.documentElement.scrollWidth,
                    heading:document.querySelector('h1')?.textContent,
                    controls:[...document.querySelectorAll('input,select,button')].filter(x=>x.getBoundingClientRect().width>0 && x.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})).map(x=>({tag:x.tagName,id:x.id,text:x.textContent?.slice(0,120),class:x.className,left:x.getBoundingClientRect().left,right:x.getBoundingClientRect().right}))})""")
                assert dom["lang"] == locale and dom["dir"] == ("rtl" if locale == "ar" else "ltr")
                assert dom["heading"] and dom["scroll"] <= width + 1, dom
                assert not errors, errors
                assert len(external) == start_external
                assert all(method == "GET" or path == "/api/v1/auth/refresh" for method,path in requests[before:]), requests[before:]
                counts = Counter(path.split('?')[0] for _,path in requests[before:])
                budgets = {'/api/v1/users/me':8,'/api/v1/users/me/access-status':4,'/api/v1/auth/refresh':6}
                assert len(requests[before:]) <= 30, counts
                assert all(counts[path] <= limit for path,limit in budgets.items()), counts
                return {"dom":dom,"requests":dict(Counter(str(item) for item in requests[before:])),"request_budgets":{**budgets,'total':30}}
            for locale in ("en","uz","ru","ar"):
                for width in (320,390,768,1440):
                    for name,path in surfaces:
                        def mobile(path=path, locale=locale, width=width, name=name):
                            evidence = load(path, locale, width)
                            if width <= 390:
                                page.screenshot(path=str(OUT / f"{locale}-{name}-{width}.png"), full_page=True)
                            for control in evidence["dom"]["controls"]:
                                assert control["left"] >= -1 and control["right"] <= width + 1, control
                            if name == "explorer":
                                menu = page.locator('details').first
                                menu.locator('summary').click()
                                assert menu.evaluate("""x => [...x.querySelectorAll('button')].filter(b=>b.checkVisibility()).every(b=>{const r=b.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth;})""")
                                menu.locator('summary').click()
                            if name == "bid-preparation":
                                assert page.evaluate("""() => {const h=document.querySelector('h1').getBoundingClientRect();const badges=[...document.querySelectorAll('.rounded-full')];return badges.every(b=>{const r=b.getBoundingClientRect();return r.right<=h.left||r.left>=h.right||r.bottom<=h.top||r.top>=h.bottom;});}""")
                            if width == 320:
                                page.screenshot(path=str(OUT / f"{locale}-{name}-320.png"), full_page=True)
                            page.keyboard.press("Tab")
                            assert page.evaluate("document.activeElement !== document.body")
                            return evidence
                        case(f"mobile/{locale}/{width}/{name}", mobile)
                    def recovery(locale=locale,width=width):
                        controls["outage"] = True
                        response = page.goto(BASE + "/dashboard/tenders?view=all", wait_until="networkidle")
                        assert response.status == 503 and "pending-approval" not in page.url
                        assert page.locator('html').get_attribute('lang') == locale
                        assert page.locator('a[href=""]').is_visible()
                        controls["outage"] = False
                        page.locator('a[href=""]').click()
                        page.wait_for_load_state('networkidle')
                        assert "/dashboard/tenders" in page.url and "view=all" in page.url
                        return {"outage_status":503,"retry_url":page.url}
                    case(f"session/{locale}/{width}/outage-retry", recovery)
            controls["outage"] = False
            for name,path in surfaces + [("details","tenders/s72-tender"),("compliance","tenders/s72-tender/compliance"),("readiness","readiness-vault"),("settings","settings")]:
                case(f"production-passivity/{name}", lambda path=path: load(path,"en",390))
            for name,path in surfaces + [("settings","settings")]:
                def navigate(path=path):
                    load("settings","en",390)
                    before = len(requests)
                    page.locator(f'aside a[href="/dashboard/{path.split("?")[0]}"]').click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(300)
                    counts = Counter(str(item) for item in requests[before:])
                    assert "pending-approval" not in page.url
                    return dict(counts)
                case(f"production-client-navigation/{name}", navigate)
            for name,path in [("proposals","bid-preparation"),("readiness","readiness-vault")]:
                def pagination(path=path):
                    controls["pagination"] = True
                    load(path,"en",390)
                    page.get_by_role("button",name="Next",exact=True).click()
                    page.wait_for_url("**page=2")
                    page.wait_for_load_state("networkidle")
                    expect(page.get_by_role("button",name="Previous",exact=True)).to_be_enabled()
                    expect(page.get_by_role("button",name="Next",exact=True)).to_be_disabled()
                    controls["pagination"] = False
                    return {"url":page.url}
                case(f"pagination/{name}", pagination)
            def document_viewer():
                load("tenders/s72-tender","en",390)
                before = len(requests)
                results = [page.evaluate("""async path=>{const r=await fetch(path);return {status:r.status,body:await r.json()};}""",path) for path in ('/api/documents/missing-fixture','/document-preview/missing-fixture')]
                assert all(result["status"] == 404 for result in results), results
                assert not external
                assert all(method == "GET" or path == "/api/v1/auth/refresh" for method,path in requests[before:])
                return {"status":404,"source_requests":0,"requests":dict(Counter(str(x) for x in requests[before:]))}
            case("production-passivity/document-viewer-missing",document_viewer)
            def locale_spoof():
                s72.State.users['s72-token-a']['ui_locale']='uz'
                context.set_extra_http_headers({'x-plasma-persisted-ui-locale':'ar'})
                try:
                    page.goto(BASE+'/dashboard/settings',wait_until='networkidle')
                    assert page.locator('html').get_attribute('lang') == 'uz'
                finally: context.set_extra_http_headers({})
                return {'persisted_locale':'uz','spoofed_locale':'ar','result':'uz'}
            case('locale/spoofed-persisted-header',locale_spoof)
            def locale_isolation():
                load('settings','en',390)
                s72.State.users['s72-token-b']['ui_locale'] = 'ru'
                other_token = subprocess.check_output(['node','--input-type=module','-e',token_js],cwd=FRONT,env={**env,'TEST_ACCESS_TOKEN':'s72-token-b'},text=True).strip()
                other = browser.new_context(viewport={'width':390,'height':844})
                other.route('**/*',network)
                other.add_cookies([{'name':'__Secure-authjs.session-token','value':other_token,'domain':'localhost','path':'/','secure':True}])
                try:
                    other_page = other.new_page()
                    other_page.goto(BASE+'/dashboard/settings',wait_until='networkidle')
                    assert other_page.locator('html').get_attribute('lang') == 'ru'
                    assert page.locator('html').get_attribute('lang') == 'en'
                finally: other.close()
                return {'user_a':'en','user_b':'ru','isolated':True}
            case('locale/two-user-isolation',locale_isolation)
            def revoked():
                load('settings','en',390)
                controls['revoked'] = True
                try:
                    response = page.goto(BASE+'/dashboard/tenders',wait_until='networkidle')
                    assert urlparse(page.url).path == '/' and response.status == 200
                finally: controls['revoked'] = False
                return {'next_navigation':'/','authorization_ttl':0}
            case('session/revocation-next-navigation',revoked)
            def expiry():
                context.clear_cookies()
                page.goto(BASE + "/dashboard/tenders", wait_until="networkidle")
                assert urlparse(page.url).path == "/"
                assert "/login" not in page.url
                return {"path":urlparse(page.url).path}
            case("session/expired-real-sign-in", expiry)

            # Real HTTP backend route/dependency execution driven from Chromium.
            # Only database persistence and Auth.js issuance are controlled fixtures.
            sys.path.insert(0, str(ROOT / "backend"))
            import uvicorn
            from fastapi import FastAPI
            from app.api.endpoints import auth, tenders
            from app.core import auth_bridge
            from app.core.config import settings
            from app.core.security import create_access_token, get_current_user as current_account
            from app.db.session import get_db
            from test_release_security import IdentityDB, synthetic_user, proof_payload, BRIDGE_SECRET
            db = IdentityDB(synthetic_user())
            api = FastAPI()
            api.include_router(auth.router,prefix="/auth")
            api.include_router(tenders.router,prefix="/tenders")
            api.dependency_overrides[get_db] = lambda: db
            @api.get("/health")
            async def health(): return {"fixture":True}
            # Browser multipart requests exercise the real upload route with bounded
            # synthetic parser/model outcomes. Authorization is covered above.
            from types import SimpleNamespace
            from uuid import uuid4
            from tempfile import TemporaryDirectory
            from app.api.endpoints import proposals
            from app.api.deps import require_approved_pilot_access
            from app.core import uploads
            from app.core.http_hardening import HardenedHTTPMiddleware
            from test_release_uploads import permit
            upload_user = SimpleNamespace(id=uuid4(),company_name='Synthetic',core_services='',past_experience='')
            upload_proposal = SimpleNamespace(id=uuid4(),structured_data={'prior':'preserved'},ai_confidence_score=10,tender=SimpleNamespace(budget=1000))
            upload_db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda:upload_proposal)),commit=AsyncMock(),rollback=AsyncMock())
            upload_api = FastAPI()
            upload_api.add_middleware(HardenedHTTPMiddleware)
            upload_api.include_router(proposals.router,prefix='/api/v1/proposals')
            upload_api.dependency_overrides[get_db] = lambda: upload_db
            upload_api.dependency_overrides[current_account] = lambda: upload_user
            upload_api.dependency_overrides[require_approved_pilot_access] = lambda: upload_user
            api.mount('/upload-fixture',upload_api)
            api_server = uvicorn.Server(uvicorn.Config(api,host="127.0.0.1",port=8124,log_level="critical",access_log=False))
            threading.Thread(target=api_server.run,daemon=True).start()
            for _ in range(100):
                if api_server.started: break
                time.sleep(.05)
            page.goto("http://127.0.0.1:8124/health")
            def fetch(path, headers=None, body=None):
                return page.evaluate("""async ({path,headers,body})=>{const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',...headers},body:body?JSON.stringify(body):undefined});return {status:r.status,body:await r.json()};}""", {"path":path,"headers":headers or {},"body":body})
            for route in ("", "/00000000-0000-4000-8000-000000000001", "/00000000-0000-4000-8000-000000000001/details", "/00000000-0000-4000-8000-000000000001/documents", "/00000000-0000-4000-8000-000000000001/decision-snapshot"):
                for state,expected in (("anonymous",401),("invalid",401),("pending",403),("rejected",401),("disabled",401),("stale",401),("approved",200),("operator",200),("admin",200)):
                    def authority(route=route,state=state,expected=expected):
                        db.user = synthetic_user(state=state if state in {"pending","rejected","disabled"} else "approved",role=state if state in {"operator","admin"} else "pilot_user")
                        db.reads.clear()
                        bearer = create_access_token({"sub":str(db.user.id),"auth_version":2 if state == "stale" else 3})
                        headers = {} if state == "anonymous" else {"Authorization":"Bearer " + ("invalid" if state == "invalid" else bearer)}
                        result = fetch("/tenders" + route,headers)
                        assert result["status"] == (404 if expected == 200 and route else expected), result
                        if expected != 200: assert all("FROM tenders" not in query for query in db.reads)
                        return {"status":result["status"],"domain_writes":len(db.writes)}
                    case(f"backend-auth/{state}/{route or 'list'}",authority)
            consumed = set()
            async def consume(jti):
                if jti in consumed: return False
                consumed.add(jti)
                return True
            with patch.object(settings,"AUTH_BRIDGE_SECRET",BRIDGE_SECRET), patch.object(auth_bridge,"consume_assertion",consume):
                for attack in ("approved-no-proof","admin-no-proof","operator-no-proof","forged-subject","wrong-audience","wrong-issuer","expired","tampered","email-injection"):
                    def impersonation(attack=attack):
                        payload = proof_payload()
                        if attack.endswith('no-proof'): payload.bridge_assertion = None; payload.email = attack + '@example.invalid'
                        elif attack == 'forged-subject': payload.google_id = 'forged'
                        elif attack == 'wrong-audience': payload = proof_payload(aud='wrong')
                        elif attack == 'wrong-issuer': payload = proof_payload(iss='wrong')
                        elif attack == 'expired': payload = proof_payload(iat=int(time.time())-120,exp=int(time.time())-60)
                        elif attack == 'tampered': payload.bridge_assertion += 'tamper'
                        else: payload.email = 'admin@example.invalid'
                        db.reads.clear(); before = len(db.writes)
                        result = fetch('/auth/google',body=payload.model_dump())
                        assert result['status'] == 401 and not db.reads and len(db.writes) == before
                        return {'status':401,'domain_writes':0}
                    case('impersonation/'+attack,impersonation)
                for role in ('approved','operator','admin'):
                    def login(role=role):
                        db.user = synthetic_user(role=role if role != 'approved' else 'pilot_user')
                        result = fetch('/auth/google',body=proof_payload().model_dump())
                        assert result['status'] == 200 and result['body']['access_token']
                        return {'status':200,'role':result['body']['platform_role']}
                    case('verified-login/'+role,login)
                def replay():
                    db.user = synthetic_user()
                    payload = proof_payload().model_dump()
                    assert fetch('/auth/google',body=payload)['status'] == 200
                    db.user.approval_status = 'disabled'
                    db.user.auth_version += 1
                    assert fetch('/auth/google',body=payload)['status'] == 401
                    db.user.approval_status = 'approved'
                    assert fetch('/auth/google',body=payload)['status'] == 401
                    return {'disabled_replay':401,'restored_replay':401}
                case('session/bridge-replay-after-disable-and-restore',replay)
            context.clear_cookies()  # Upload fixture uses isolated authority; no bridge cookie crosses this boundary.
            for outcome,expected in [('valid',200),('extension',415),('signature',415),('parse',422),('model',502)]:
                def multipart(outcome=outcome,expected=expected):
                    from fastapi import HTTPException
                    upload_proposal.structured_data = {'prior':'preserved'}
                    upload_proposal.ai_confidence_score = 10
                    upload_db.commit.reset_mock()
                    parser = AsyncMock(return_value='Synthetic parsed requirements')
                    model = AsyncMock(return_value={'summary':'Synthetic summary','items':[],'delivery_days':30})
                    if outcome == 'parse': parser.side_effect=HTTPException(422,'PDF could not be parsed')
                    if outcome == 'model': model.side_effect=RuntimeError('SECRET_SENTINEL CUSTOMER_TEXT_SENTINEL')
                    with TemporaryDirectory(prefix='plasma-browser-upload-') as temporary, ExitStack() as mocks:
                        mocks.enter_context(patch.object(proposals,'__file__',str(Path(temporary)/'app/api/endpoints/proposals.py')))
                        mocks.enter_context(patch.object(uploads,'upload_permit',permit))
                        mocks.enter_context(patch.object(uploads,'parse_uploaded_pdf',parser))
                        mocks.enter_context(patch.object(uploads,'analyze_uploaded_pdf',model))
                        page.evaluate("""()=>{document.body.innerHTML='<input type="file" id="upload-fixture">';}""")
                        page.locator('#upload-fixture').set_input_files({'name':'source.txt' if outcome=='extension' else '../../source.pdf','mimeType':'application/pdf','buffer':b'not-pdf' if outcome=='signature' else b'%PDF-1.4 synthetic'})
                        result=page.evaluate("""async path=>{const form=new FormData();form.append('file',document.querySelector('input').files[0]);const r=await fetch(path,{method:'POST',body:form});return {status:r.status,body:await r.text()};}""", '/upload-fixture/api/v1/proposals/'+str(upload_proposal.id)+'/upload-tz')
                        assert result['status']==expected,result
                        assert 'SENTINEL' not in result['body']
                        if outcome!='valid':
                            assert upload_proposal.structured_data=={'prior':'preserved'}
                            upload_db.commit.assert_not_awaited()
                            assert not list(Path(temporary).rglob('*.pdf'))
                        if outcome in {'extension','signature','parse'}: model.assert_not_awaited()
                        assert not list(Path(temporary).rglob('upload-*.pdf'))
                    return {'status':expected,'commits':upload_db.commit.await_count,'temporary_files_cleaned':True}
                case('upload/browser-multipart/'+outcome,multipart)
            browser.close()
    finally:
        if api_server: api_server.should_exit = True
        if os.name == 'posix':
            try: os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError: pass
        else: proc.terminate()
        proc.wait(timeout=20)
        server.shutdown(); server.server_close(); log.close()
        result = {"method":"Real Chromium against local production Next.js and controlled HTTP API fixtures; backend security cases execute real route/dependency code with synthetic DB and signed assertion fixtures", "cases":rows,"external_requests":external,
                  "passed":sum(row['status']=='PASS' for row in rows),"failed":sum(row['status']=='FAIL' for row in rows)}
        (OUT/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    return 0 if len(rows) >= 100 and all(row['status']=='PASS' for row in rows) and not external else 1


if __name__ == '__main__':
    raise SystemExit(main())
