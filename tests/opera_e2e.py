"""Actual Opera UI on Windows/macOS/Mint; synthetic APIs, no NAS execution."""
import json
import os
import platform
import ssl
import urllib.request
from pathlib import Path

from desktop_fixture import desktop_fixture
from execution_ui_e2e import backup_case, restore_case
from retail_opera import opera_binary
from browser_navigation import open_fixture


def panels(browser, output):
    from playwright.sync_api import expect
    with desktop_fixture() as (api,url,cert):
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(cert))))
        with opener.open(url,timeout=10) as response:assert response.status==200
        context=browser.new_context(ignore_https_errors=True,viewport={'width':1100,'height':1150},service_workers='block')
        page=context.new_page();page.set_default_timeout(15000)
        errors=[];network_errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('requestfailed',lambda request:network_errors.append({'url':request.url,'failure':request.failure}))
        page.on('console',lambda message:network_errors.append({'console':message.text}) if message.type=='error' else None)
        try:
            open_fixture(page,url,ready_selector='.pcc-login input')
            ua=page.evaluate('navigator.userAgent')
            if 'OPR/' not in ua:raise RuntimeError('Browser is not identifiable as retail Opera: '+ua)
            (output/'environment.json').write_text(json.dumps({'os':platform.platform(),'binary':opera_binary(),'version':browser.version,'user_agent':ua,'coverage':'actual Opera; synthetic API; no NAS execution'},indent=2),encoding='utf-8')
            page.locator('.pcc-login input').fill('fixture-only-password');page.locator('.pcc-login button').click()
            expect(page.locator('.pcc-nav')).to_be_visible()
            def tab(key):
                button=page.locator('.pcc-nav button').nth(['dashboard','backup','restore','history','settings'].index(key))
                button.click();expect(button).to_have_attribute('aria-selected','true')
            for language,theme,width in [('en','Light',1100),('pl','Dark',1100),('en','System',430),('pl','Light',430)]:
                page.set_viewport_size({'width':width,'height':1150});tab('settings')
                page.locator('[data-language]').select_option(language)
                expect(page.locator('html')).to_have_attribute('lang',language)
                page.locator(f'[data-theme-choice={theme}]').click()
                expect(page.locator('#pcc-app')).to_have_attribute('data-theme',theme.lower())
                for key in ('dashboard','backup','restore','history','settings'):
                    tab(key);root=page.locator(f'[data-panel={key}]');expect(root).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),key+' horizontal overflow'
                    if key in ('backup','restore','history'):
                        scroller=root.locator({'history':'[data-events]','restore':'[data-archive-list]','backup':'[data-archives]'}[key])
                        expect(scroller.locator('.pcc-event-row' if key=='history' else '.pcc-archive-row')).to_have_count(20 if key=='history' else 13)
                        expect(scroller).to_be_visible()
                        assert scroller.evaluate('e=>e.scrollHeight>e.clientHeight')
                        scroller.evaluate('e=>e.scrollTop=e.scrollHeight');assert scroller.evaluate('e=>e.scrollTop>0')
                        scroller.evaluate('e=>e.scrollTop=0');scroller.locator('input').first.check()
                        expect(scroller.locator('input:checked')).to_have_count(1)
                    if theme=='Light':expect(root.locator('h3' if key=='dashboard' else 'h2').first).to_have_css('color','rgb(0, 0, 0)')
                    page.screenshot(path=str(output/f'{key}-{language}-{theme}-{width}.png'),full_page=True)
                tab('dashboard');root=page.locator('[data-panel=dashboard]')
                for state in ('STOPPED','RUNNING'):
                    api.plex=state;expect(root.locator('[data-plex-state]')).to_have_attribute('data-plex-state',state)
                root.locator('[data-password]').click();expect(root.locator('dialog[open]')).to_be_visible();root.locator('[data-close]').click()
            tab('dashboard');page.locator('[data-logout]').click();expect(page.locator('.pcc-login')).to_be_visible()
            assert not api.authenticated and not errors,errors
        except BaseException:
            try:page.screenshot(path=str(output/'failure.png'),full_page=True)
            except Exception:pass
            (output/'failure.html').write_text(page.content(),encoding='utf-8')
            print('Opera page errors:',errors,flush=True)
            print('Opera network errors:',network_errors,flush=True)
            raise
        finally:context.close()


def main():
    from playwright.sync_api import sync_playwright
    target=os.environ.get('PCC_DESKTOP_TARGET','local')
    if target not in ('windows','macos','mint','local'):raise ValueError('Unsupported Opera target')
    if target=='windows' and platform.system()!='Windows':raise RuntimeError('Windows target requires Windows')
    if target=='macos' and platform.system()!='Darwin':raise RuntimeError('macOS target requires macOS')
    if target=='mint' and (platform.system()!='Linux' or not Path('/etc/linuxmint/info').is_file()):raise RuntimeError('Mint metadata missing')
    container=os.environ.get('PCC_MINT_CONTAINER_CI_ONLY')=='1'
    if container and (os.environ.get('CI')!='true' or target!='mint'):raise RuntimeError('Container flag requires disposable Mint CI')
    output=Path('dist/browser-screenshots')/f'desktop-{target}-opera';output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(executable_path=opera_binary(),chromium_sandbox=not container)
        try:
            print('Actual Opera:',opera_binary(),browser.version,platform.platform(),flush=True)
            panels(browser,output)
            for language,theme,width in [('en','light',900),('pl','dark',900),('en','system',390),('pl','light',390)]:
                backup_case(browser,output,language,theme,width)
                restore_case(browser,output,language,theme,width)
            backup_case(browser,output,'en','light',900,check_only=True)
            print('Opera PASS: five-panel UI and execution dialogs (synthetic API only)',flush=True)
        finally:browser.close()


if __name__=='__main__':main()
