"""Real Safari/Firefox on macOS, and Safari in Apple iPhone/iPad simulators.

This is not WebKit device emulation. Firefox iOS/iPadOS, physical devices and
native gallery/download dialogs are explicitly outside this CI test's claims.
"""
import base64
import io
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.safari.service import Service as SafariService
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

from apple_fixture import apple_fixture


def command(*args, timeout=120):
    print('Apple CI command:', ' '.join(args), flush=True)
    try:
        return subprocess.check_output(args, text=True, timeout=timeout).strip()
    except subprocess.TimeoutExpired as error:
        partial = error.output or b''
        if isinstance(partial, bytes): partial = partial.decode('utf-8', errors='replace')
        print('Timed-out command output:', partial[-4000:], flush=True)
        raise


def create_simulator(tablet):
    """Select installed runtime/hardware, but create only our own disposable VM."""
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('PCC_APPLE_CI_ONLY') != '1':
        raise RuntimeError('Simulator tests require explicit disposable CI opt-in')
    devices = json.loads(command('xcrun','simctl','list','devices','available','--json'))['devices']
    candidates = []
    for runtime, rows in devices.items():
        if '.iOS-' not in runtime:
            continue
        for row in rows:
            if row.get('isAvailable') and row['name'].startswith('iPad' if tablet else 'iPhone'):
                candidates.append((runtime, row))
    if not candidates:
        raise RuntimeError('No suitable installed iOS/iPadOS simulator runtime')
    candidates.sort(key=lambda item:tuple(int(p) for p in item[0].split('.iOS-')[-1].split('-')), reverse=True)
    runtime = candidates[0][0]
    same_runtime = [row for candidate, row in candidates if candidate == runtime]
    selected = next((row for row in same_runtime if row['name']=='iPhone 16 Pro Max'), same_runtime[0]) if not tablet else same_runtime[0]
    name = 'PCC-iPad' if tablet else 'PCC-iPhone'
    identifier = command('xcrun','simctl','create',name,selected['deviceTypeIdentifier'],runtime)
    try:
        command('xcrun','simctl','boot',identifier)
        command('xcrun','simctl','bootstatus',identifier,'-b',timeout=360)
        simulator_app=Path(command('xcode-select','-p'))/'Applications'/'Simulator.app'
        command('open','-a',str(simulator_app),'--args','-CurrentDeviceUDID',identifier)
        command('xcrun','simctl','launch',identifier,'com.apple.mobilesafari')
    except BaseException:
        subprocess.run(['xcrun','simctl','shutdown',identifier],check=False,timeout=60)
        subprocess.run(['xcrun','simctl','delete',identifier],check=False,timeout=60)
        raise
    print('Apple simulator:',selected['name'],runtime,identifier,flush=True)
    return identifier


def exercise(driver, fixture, output, *, mobile):
    wait = WebDriverWait(driver, 20)
    def visible(selector):
        return wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR,selector)))
    def click(selector):
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,selector))).click()
    def text(selector, expected):
        wait.until(lambda _: expected in visible(selector).text)
    def tab(name):
        selector=f'.pcc-nav button[data-apple-tab="{name}"]'
        # Tab keys are maintained on the browser test side, not production DOM.
        driver.execute_script("document.querySelectorAll('.pcc-nav button').forEach((e,i)=>e.dataset.appleTab=['dashboard','backup','restore','history','settings'][i])")
        click(selector)
        wait.until(lambda _:driver.find_element(By.CSS_SELECTOR,selector).get_attribute('aria-selected')=='true')
        assert driver.execute_script('return document.documentElement.scrollWidth<=innerWidth'),name+' horizontal overflow'
    driver.get(fixture['url'])
    visible('.pcc-login input').send_keys(fixture['password'])
    assert driver.execute_script("return document.querySelector('.pcc-login input').value.length")==len(fixture['password']),'WebDriver did not populate the password input'
    click('.pcc-login button')
    visible('.pcc-nav')
    driver.execute_script("window.__pccAppleErrors=[];addEventListener('error',e=>window.__pccAppleErrors.push(String(e.message)));addEventListener('unhandledrejection',e=>window.__pccAppleErrors.push(String(e.reason)));")
    print('Browser UA:',driver.execute_script('return navigator.userAgent'),flush=True)
    text('[data-account-active]','ACTIVE')
    # Upload through the actual file input change handler, avoiding native pickers.
    image=io.BytesIO();Image.new('RGB',(48,36),'#2a70af').save(image,format='PNG')
    driver.execute_script("""const bytes=Uint8Array.from(atob(arguments[0]),c=>c.charCodeAt(0));
        const files=new DataTransfer();files.items.add(new File([bytes],'apple-test.png',{type:'image/png'}));
        const input=document.querySelector('[data-photo-file]');input.files=files.files;
        input.dispatchEvent(new Event('change',{bubbles:true}));""",base64.b64encode(image.getvalue()).decode())
    visible('[data-profile-photo]')
    wait.until(lambda _:driver.execute_script("return document.querySelector('[data-profile-photo]').naturalWidth===512"))
    tab('backup')
    wait.until(lambda _:len(driver.find_elements(By.CSS_SELECTOR,'[data-panel=backup] .pcc-archive-row'))==13)
    click('[data-panel=backup] input[type=checkbox]')
    visible('[data-panel=backup] .pcc-selected')
    assert not driver.find_element(By.CSS_SELECTOR,'[data-create]').is_enabled()
    # Import into the already open panel without any history/manifest dependency.
    imported='TrueNASPlexConfig_2026.09.30_08.15.00.tar.gz'
    shutil.copyfile(next(fixture['archives'].glob('*.tar.gz')),fixture['archives']/imported)
    click('[data-panel=backup] [data-refresh]')
    wait.until(lambda _:len(driver.find_elements(By.CSS_SELECTOR,'[data-panel=backup] .pcc-archive-row'))==14)
    tab('restore')
    wait.until(lambda _:len(driver.find_elements(By.CSS_SELECTOR,'[data-panel=restore] input[type=radio]'))==14)
    assert not driver.find_elements(By.CSS_SELECTOR,'[data-panel=restore] input:checked')
    click('[data-panel=restore] input[type=radio]')
    click('[data-restore-action=validate]')
    text('[data-validation-notice]','not confirmed stopped')
    assert not driver.find_element(By.CSS_SELECTOR,'[data-restore-action=validate]').is_enabled()
    click('[data-restore-action=cancel]')
    wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR,'[data-restore-action=cancel]')))
    tab('history')
    visible('.pcc-event-row')
    assert 'Archive detected' in driver.find_element(By.CSS_SELECTOR,'[data-events]').text
    row=driver.find_element(By.CSS_SELECTOR,'.pcc-event-row input')
    event_id=int(row.get_attribute('data-event-id'))
    row.click()
    # Verify actual log bytes through authenticated API on every Apple platform.
    # Native Save/Files UI is not controlled or claimed as tested on iOS/iPadOS.
    result=driver.execute_async_script("""const id=arguments[0],done=arguments[arguments.length-1];
      (async()=>{const session=await(await fetch('/api/session')).json();
      const response=await fetch('/api/history/download',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:JSON.stringify({ids:[id]})});
      done({ok:response.ok,type:response.headers.get('Content-Type'),text:await response.text()});})().catch(e=>done({error:String(e)}));""",event_id)
    assert result.get('ok') and result['text'] and result['type'].startswith('text/plain'),result
    click('[data-clear]');visible('[data-panel=history] dialog');click('[data-panel=history] [data-cancel]')
    wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR,'[data-panel=history] dialog')))
    click('[data-clear]');visible('[data-panel=history] dialog');click('[data-panel=history] [data-confirm]')
    wait.until(lambda _:fixture['app'].history.detail(event_id) is None)
    assert (fixture['archives']/'Logs'/'fixture-permanent.log').read_text()=='Permanent CI log must survive History clearing.'
    heights=[]
    for theme in ('Light','Dark'):
        tab('settings');click(f'[data-theme-choice={theme}]')
        wait.until(lambda _:driver.find_element(By.ID,'pcc-app').get_attribute('data-theme')==theme.lower())
        Select(driver.find_element(By.CSS_SELECTOR,'[data-language]')).select_by_value('pl')
        text('[data-about]','O aplikacji')
        heights=[]
        for index,name in enumerate(('dashboard','backup','restore','history','settings'),1):
            tab(name)
            section=visible(f'[data-panel={name}]')
            heights.append(section.size['height'])
            for selector in ('[data-archives]','[data-archive-list]','[data-events]'):
                for scroller in section.find_elements(By.CSS_SELECTOR,selector):
                    assert driver.execute_script('return arguments[0].scrollHeight>arguments[0].clientHeight',scroller)
                    driver.execute_script('arguments[0].scrollTop=arguments[0].scrollHeight',scroller)
                    assert driver.execute_script('return arguments[0].scrollTop>0',scroller)
                    driver.execute_script('arguments[0].scrollTop=0',scroller)
            driver.save_screenshot(str(output/f'{theme.lower()}-{index}.png'))
        if not mobile:
            assert max(heights)-min(heights)<3,heights
    driver.refresh();visible('.pcc-nav')
    assert driver.find_element(By.ID,'pcc-app').get_attribute('data-theme')=='dark'
    assert 'Pulpit' in driver.find_element(By.CSS_SELECTOR,'.pcc-nav').text
    # Photo controls must work by hover/focus on desktop and without hover on iOS.
    tab('dashboard');visible('[data-profile-photo]')
    if not mobile:ActionChains(driver).move_to_element(driver.find_element(By.CSS_SELECTOR,'.pcc-avatar')).perform()
    click('[data-photo-remove]');visible('[data-photo-dialog]');click('[data-photo-confirm]')
    wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR,'[data-profile-photo]')))
    assert not driver.execute_script('return window.__pccAppleErrors||[]')
    # Verify change-password dialog, validation and session revocation.
    click('[data-password]');visible('[data-panel=dashboard] dialog')
    for name,value in (('current',fixture['password']),('password','ci-apple-new-password'),('confirmation','ci-apple-new-password')):
        driver.find_element(By.CSS_SELECTOR,f'input[name={name}]').send_keys(value)
    click('[data-save]');visible('.pcc-login input').send_keys('ci-apple-new-password')
    click('.pcc-login button');visible('.pcc-nav')
    click('[data-panel=dashboard] [data-logout]');visible('.pcc-login')


def main():
    mode=os.environ.get('PCC_APPLE_TARGET','safari-macos')
    if mode not in ('safari-macos','firefox-macos','safari-ios','safari-ipados'):
        raise ValueError('Unknown Apple test target')
    if platform.system()!='Darwin' or os.environ.get('GITHUB_ACTIONS')!='true':
        raise RuntimeError('Apple tests run only on disposable macOS CI runners')
    output=Path('dist/browser-screenshots')/mode;output.mkdir(parents=True,exist_ok=True)
    driver=None;simulator=None;trusted_hash=None;fixture_state=None
    print(command('sw_vers'),flush=True)
    try:
        with apple_fixture() as fixture:
            fixture_state=fixture
            if mode.startswith('safari'):
                trusted_hash=command('openssl','x509','-in',str(fixture['cert']),'-noout','-fingerprint','-sha1').split('=')[-1].replace(':','')
                command('sudo','security','add-trusted-cert','-d','-r','trustRoot','-k','/Library/Keychains/System.keychain',str(fixture['cert']))
                options=webdriver.SafariOptions()
                if mode in ('safari-ios','safari-ipados'):
                    simulator=create_simulator(mode=='safari-ipados')
                    command('xcrun','simctl','keychain',simulator,'add-root-cert',str(fixture['cert']))
                    # openurl accepts OS-registered URL schemes; about:blank
                    # is not one on iOS. Open the actual trusted HTTPS fixture
                    # so Safari has a web content target before driver attach.
                    command('xcrun','simctl','openurl',simulator,fixture['url'])
                    options.platform_name='iOS'
                    options.set_capability('safari:useSimulator',True)
                    options.set_capability('safari:deviceUDID',simulator)
                driver=webdriver.Safari(options=options,service=SafariService(log_output=str(output/'safaridriver.log')))
            else:
                options=webdriver.FirefoxOptions();options.binary_location='/Applications/Firefox.app/Contents/MacOS/firefox'
                options.accept_insecure_certs=True
                executable=shutil.which('geckodriver')
                if not executable:
                    candidate=Path(os.environ.get('GECKOWEBDRIVER',''))/'geckodriver'
                    executable=str(candidate) if candidate.is_file() else None
                driver=webdriver.Firefox(service=FirefoxService(executable_path=executable) if executable else FirefoxService(),options=options)
            print('WebDriver capabilities:',json.dumps(driver.capabilities),flush=True)
            driver.set_script_timeout(30);driver.set_page_load_timeout(60)
            mobile=mode in ('safari-ios','safari-ipados')
            if not mobile:driver.set_window_size(1440,1080)
            exercise(driver,fixture,output,mobile=mobile)
            print('Apple interface checks passed:',mode,flush=True)
    except BaseException:
        if fixture_state is not None:print('Apple fixture API status audit:',json.dumps(fixture_state['requests'][-40:]),flush=True)
        if simulator:
            subprocess.run(['xcrun','simctl','io',simulator,'screenshot',str(output/'simulator-failure.png')],check=False,timeout=30)
        if driver is not None:
            try:
                driver.save_screenshot(str(output/'failure.png'))
                (output/'failure.html').write_text(driver.page_source)
            except Exception:pass
        raise
    finally:
        if driver is not None:
            try:driver.quit()
            except Exception:pass
        if trusted_hash:
            subprocess.run(['sudo','security','delete-certificate','-Z',trusted_hash,'/Library/Keychains/System.keychain'],check=False)
        if simulator:
            subprocess.run(['xcrun','simctl','shutdown',simulator],check=False)
            subprocess.run(['xcrun','simctl','delete',simulator],check=False)


if __name__=='__main__':main()
