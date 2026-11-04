"""Retail Windows/Mint browsers, actual UI, synthetic loopback HTTPS API only.

Never connects to a NAS. Does not claim backend execution, OS file pickers or
physical desktop acceptance. Browser/OS versions and screenshots are recorded.
"""
import json
import os
import platform
import shutil
from pathlib import Path
import ssl
import urllib.request

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from desktop_fixture import desktop_fixture
from execution_ui_e2e import NAME


def installed_browser(engine):
    if engine not in ('chrome','firefox','msedge'): raise ValueError('Unsupported retail browser')
    names={'chrome':('google-chrome-stable','google-chrome'), 'firefox':('firefox',), 'msedge':('microsoft-edge',)}
    for name in names[engine]:
        found=shutil.which(name)
        if found:return found
    relative={'chrome':'Google/Chrome/Application/chrome.exe','firefox':'Mozilla Firefox/firefox.exe','msedge':'Microsoft/Edge/Application/msedge.exe'}[engine]
    if platform.system()=='Windows':
        for base in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
            candidate=Path(os.environ.get(base,'__missing__'))/relative
            if candidate.is_file():return str(candidate)
    raise RuntimeError('Required installed retail browser missing: '+engine)


def browser_for(engine):
    binary=installed_browser(engine)
    if engine == 'firefox':
        options = webdriver.FirefoxOptions();options.add_argument('-headless')
        options.binary_location = binary
        options.accept_insecure_certs = True  # Only the disposable fixture cert.
        return webdriver.Firefox(options=options)
    if engine not in ('chrome','msedge'): raise ValueError('Choose chrome, firefox or msedge')
    options = webdriver.ChromeOptions() if engine=='chrome' else webdriver.EdgeOptions()
    options.binary_location = binary
    options.add_argument('--headless=new');options.accept_insecure_certs = True
    if os.environ.get('PCC_MINT_CONTAINER_CI_ONLY')=='1':
        if os.environ.get('CI')!='true' or os.environ.get('PCC_DESKTOP_TARGET')!='mint':
            raise RuntimeError('Container browser flag requires disposable Mint CI')
        options.add_argument('--no-sandbox')  # Synthetic UI inside disposable CI container only.
    return webdriver.Chrome(options=options) if engine=='chrome' else webdriver.Edge(options=options)


def exercise(driver, api, url, output):
    wait = WebDriverWait(driver, 20)
    def visible(selector): return wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR,selector)))
    def click(selector): wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,selector))).click()
    def tab(key):
        index = ['dashboard','backup','restore','history','settings'].index(key)+1
        selector = f'.pcc-nav button:nth-child({index})'
        click(selector)
        wait.until(lambda _:driver.find_element(By.CSS_SELECTOR,selector).get_attribute('aria-selected')=='true')
        visible(f'[data-panel={key}]')
    def count(selector, number): wait.until(lambda _:len(driver.find_elements(By.CSS_SELECTOR,selector))==number)
    def screenshot(label): driver.save_screenshot(str(output/(label+'.png')))
    def geometry(selector):
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth+1'), selector+' page overflow'
        visible(selector)
    driver.get(url)
    visible('.pcc-login input').send_keys('fixture-only-password');click('.pcc-login button')
    visible('.pcc-nav')
    for language, theme, width in [('en','Light',1100),('pl','Dark',1100),('en','System',430),('pl','Light',430)]:
        driver.set_window_size(width, 1150)
        tab('settings')
        Select(visible('[data-language]')).select_by_value(language)
        wait.until(lambda _:driver.execute_script('return document.documentElement.lang')==language)
        click(f'[data-theme-choice={theme}]')
        wait.until(lambda _:driver.find_element(By.ID,'pcc-app').get_attribute('data-theme')==theme.lower())
        for key in ('dashboard','backup','restore','history','settings'):
            tab(key);root=f'[data-panel={key}]';geometry(root)
            if key in ('backup','restore','history'):
                attribute='data-events' if key=='history' else 'data-archives'
                row='.pcc-event-row' if key=='history' else '.pcc-archive-row'
                scroller=root+f' [{attribute}]'
                count(scroller+' '+row,20 if key=='history' else 13)
                wait.until(lambda _:driver.execute_script('return arguments[0].scrollHeight>arguments[0].clientHeight',visible(scroller)))
                scroll=visible(scroller)
                driver.execute_script('arguments[0].scrollTop=arguments[0].scrollHeight',scroll)
                assert driver.execute_script('return arguments[0].scrollTop>0',scroll)
                driver.execute_script('arguments[0].scrollTop=0',scroll)
                check=visible(scroller+' input');check.click()
                wait.until(lambda _:len(driver.find_elements(By.CSS_SELECTOR,scroller+' .pcc-selected'))==1)
                if key=='history':
                    click(root+' [data-clear]');visible(root+' dialog[open]');click(root+' [data-cancel]')
            if theme=='Light':
                heading=visible(root+' h2' if key!='dashboard' else root+' h3')
                assert driver.execute_script('return getComputedStyle(arguments[0]).color',heading)=='rgb(0, 0, 0)'
            screenshot(f'{key}-{language}-{theme}-{width}')
        tab('dashboard')
        for state in ('STOPPED','RUNNING'):
            api.plex=state
            wait.until(lambda _:visible('[data-panel=dashboard] [data-plex-state]').get_attribute('data-plex-state')==state)
        click('[data-panel=dashboard] [data-password]')
        visible('[data-panel=dashboard] dialog[open] input[name=current]')
        click('[data-panel=dashboard] [data-close]')
    # One-copy choice and execution receipts use only the synthetic fixture API.
    api.rows=[dict(api.rows[0],name=NAME)]
    driver.get(url);visible('.pcc-nav');tab('backup')
    count('[data-panel=backup] .pcc-archive-row',1)
    click('[data-panel=backup] [data-create]')
    visible('[data-backup-dialog][open]');click('[data-backup-another]')
    wait.until(lambda _:len(api.posts)==1)
    assert api.posts[0]['mode']=='ANOTHER' and api.executions==1
    api.complete()
    wait.until(lambda _:visible('[data-panel=backup] [data-operation-result]').text!='')
    api.operation={'phase':'IDLE','kind':None,'snapshot_id':None,'outcome':None,'execution_request_id':None}
    api.current=None;api.progress=None
    driver.get(url);visible('.pcc-nav');tab('restore')
    click('[data-panel=restore] input[type=radio]')
    click('[data-restore-action=validate]')
    visible('[data-validation-notice]')
    assert not visible('[data-restore-execute]').is_enabled()
    api.plex='STOPPED';click('[data-restore-action=refresh]')
    click('[data-restore-execute]');visible('[data-restore-dialog][open]')
    confirm=visible('[data-restore-dialog-confirm]');assert not confirm.is_enabled()
    visible('[data-confirm-restore]').send_keys('RESTORE')
    click('[data-restore-dialog-confirm]')
    wait.until(lambda _:len(api.posts)==2)
    assert api.posts[-1]['confirmation']=='RESTORE' and api.posts[-1]['sha256']=='b'*64
    api.complete()
    wait.until(lambda _:'sukcesem' in visible('[data-panel=restore] [data-operation-result]').text)
    assert api.plex=='STOPPED'
    screenshot('restore-completed-fixture-only')
    tab('dashboard');click('[data-logout]');visible('.pcc-login')
    assert not api.authenticated


def main():
    engine=os.environ.get('PCC_DESKTOP_BROWSER','chrome')
    target=os.environ.get('PCC_DESKTOP_TARGET','local')
    if target not in ('local','windows','mint'): raise ValueError('Unsupported desktop target')
    if target=='windows' and platform.system()!='Windows': raise RuntimeError('Windows coverage requires Windows')
    if target=='mint':
        info=Path('/etc/linuxmint/info')
        if platform.system()!='Linux' or not info.is_file(): raise RuntimeError('Mint distribution metadata missing')
        print('Mint distribution metadata:',info.read_text(),flush=True)
    output=Path('dist/browser-screenshots')/f'desktop-{target}-{engine}';output.mkdir(parents=True,exist_ok=True)
    driver=None
    with desktop_fixture() as (api,url,cert):
        # Trust the generated fixture identity for this separate health probe.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(cert))))
        with opener.open(url,timeout=10) as response: assert response.status==200
        try:
            driver=browser_for(engine)
            metadata={'os':platform.platform(),'target':target,'browser':engine,'capabilities':driver.capabilities,
                      'coverage':'synthetic HTTPS API; actual product UI; no host operations'}
            print(json.dumps(metadata,default=str),flush=True)
            (output/'environment.json').write_text(json.dumps(metadata,indent=2,default=str),encoding='utf-8')
            exercise(driver,api,url,output)
            print('PASS: five panels, EN/PL, themes, scrolling/selection, account dialogs, synthetic Backup/Restore receipts',flush=True)
        except BaseException:
            if driver:
                try:
                    driver.save_screenshot(str(output/'failure.png'))
                    (output/'failure.html').write_text(driver.page_source,encoding='utf-8')
                except Exception: pass
            print('Fixture requests:',api.calls,flush=True)
            raise
        finally:
            if driver:driver.quit()


if __name__=='__main__':main()
