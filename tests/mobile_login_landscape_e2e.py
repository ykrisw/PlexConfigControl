"""Sign-in retention and touch landscape regression checks; no NAS access."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from execution_ui_e2e import ORIGIN, STATIC
from mobile_archives_e2e import MobileFixture

def sign_in_case(browser, expect):
    context=browser.new_context(viewport={'width':844,'height':390},has_touch=True,service_workers='block')
    page=context.new_page()
    pending=[]
    def route(request):
        path=urlsplit(request.request.url).path
        if path=='/':
            body=(STATIC/'index.html').read_text().replace('/assets/panel-app.mjs','/assets/login-fixture.mjs')
            request.fulfill(content_type='text/html',body=body)
        elif path=='/assets/login-fixture.mjs':
            request.fulfill(content_type='text/javascript',body="""import {PanelClient,ApiError} from './panel-client.mjs';
PanelClient.prototype.restoreSession=function(){globalThis.expireFixture=this.onSessionExpired;return Promise.reject(new ApiError(401,{error:'Sign in required'}));};
await import('./panel-app.mjs');""")
        elif path.startswith('/assets/'):
            name=path.removeprefix('/assets/')
            assert '/' not in name and '..' not in name
            request.fulfill(content_type='text/css' if name.endswith('.css') else 'text/javascript',body=(STATIC/name).read_bytes())
        elif path=='/api/login':
            pending.append(request)
        else:
            request.fulfill(status=401,json={'error':'Sign in required'})
    page.route('**/*',route)
    try:
        page.goto(ORIGIN)
        field=page.locator('.pcc-login input[name=password]')
        expect(field).to_be_visible()
        field.fill('fixture-password-only')
        page.evaluate('globalThis.originalInput=document.querySelector(".pcc-login input")')
        for _ in range(4):
            page.evaluate('globalThis.expireFixture()')
            expect(field).to_have_value('fixture-password-only')
            assert page.evaluate('globalThis.originalInput===document.querySelector(".pcc-login input")')
        page.locator('.pcc-login button').click()
        expect(field).to_have_value('fixture-password-only')
        page.wait_for_function('document.querySelector(".pcc-login input").readOnly')
        assert len(pending)==1
        pending.pop().fulfill(status=401,json={'error':'Rejected fixture login'})
        expect(page.locator('.pcc-login [role=alert]')).to_have_text('Rejected fixture login')
        expect(field).to_have_value('fixture-password-only')
        expect(field).to_be_editable()
        context.set_default_timeout(5000)
        page.set_viewport_size({'width':390,'height':844})
        page.set_viewport_size({'width':844,'height':390})
        expect(field).to_have_value('fixture-password-only')
    finally:
        context.close()

def landscape_case(browser, expect):
    for width,height in ((844,390),(1024,768),(1366,1024)):
        fixture=MobileFixture('backup','en','dark');fixture.rows*=12
        context=browser.new_context(viewport={'width':width,'height':height},has_touch=True,color_scheme='dark',service_workers='block')
        page=context.new_page();page.route('**/*',fixture.route)
        try:
            page.goto(ORIGIN)
            for panel,title in (('backup','Backup'),('restore','Restore'),('history','History')):
                page.get_by_role('tab',name=title,exact=True).click()
                frame=page.locator('[data-panel='+panel+'] .pcc-scroll-frame')
                expect(frame).to_be_visible()
                page.evaluate('window.scrollTo(0,document.documentElement.scrollHeight)')
                page.wait_for_timeout(100)
                header=page.locator('.pcc-header').bounding_box()
                assert header['y']+header['height']<=1,(width,height,panel,header)
                assert frame.bounding_box()['height']>=128,(width,height,panel)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.evaluate('window.scrollTo(0,0)')
        finally:
            context.close()

def main():
    from playwright.sync_api import sync_playwright,expect
    engine=os.environ.get('PCC_TEST_BROWSER','webkit')
    with sync_playwright() as p:
        browser=getattr(p,engine).launch()
        try:
            sign_in_case(browser,expect)
            landscape_case(browser,expect)
            print('Sign-in retention and touch landscape: PASS ('+engine+')')
        finally:
            browser.close()

if __name__=='__main__':main()
