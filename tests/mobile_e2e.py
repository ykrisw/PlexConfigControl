"""Touch checks in Chromium device emulation or Chrome on a disposable Android VM.

This never connects to a physical phone or the user's NAS. Android mode requires
an explicit CI-only opt-in and an adb serial starting with emulator-.
"""
import io
import json
import os
import ssl
import subprocess
import tempfile
import time
import urllib.request
import uuid
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import sync_playwright, expect
from browser_e2e import fixtures
from container_smoke import docker
from android_transport import fixture_tunnel
from plexconfigcontrol.installation import password_verifier


def android_endpoint():
    if os.environ.get('CI')!='true' or os.environ.get('PCC_ANDROID_EMULATOR_ONLY')!='1':
        raise RuntimeError('Android system tests require explicit disposable CI emulator opt-in')
    devices=subprocess.check_output(['adb','devices'],text=True).splitlines()[1:]
    serials=[line.split()[0] for line in devices if line.endswith('\tdevice')]
    if len(serials)!=1 or not serials[0].startswith('emulator-'):
        raise RuntimeError('Exactly one disposable emulator must be connected; physical devices are forbidden')
    def adb(*args):
        return subprocess.check_output(['adb','-s',serials[0],*args],text=True,timeout=30).strip()
    if adb('shell','getprop','ro.kernel.qemu')!='1':
        raise RuntimeError('Connected device is not an Android emulator')
    if 'com.android.chrome' not in adb('shell','pm','list','packages','com.android.chrome'):
        raise RuntimeError('Android system image does not contain Chrome')
    print('Android system version:',adb('shell','getprop','ro.build.version.release'))
    # Only this disposable VM: suppress the first-run wizard, not application auth.
    adb('shell','am','set-debug-app','--persistent','com.android.chrome')
    adb('shell',"echo 'chrome --disable-fre --no-default-browser-check --no-first-run' > /data/local/tmp/chrome-command-line")
    adb('shell','am','force-stop','com.android.chrome')
    adb('shell','am','start','-n','com.android.chrome/com.google.android.apps.chrome.Main','-d','about:blank')
    adb('forward','tcp:9222','localabstract:chrome_devtools_remote')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        try:
            with opener.open('http://127.0.0.1:9222/json/version',timeout=2) as response:
                data=json.load(response)
                print('Android Chrome version:',data['Browser'])
                return 'http://127.0.0.1:9222', adb
        except OSError:
            time.sleep(.5)
    raise RuntimeError('Android Chrome remote debugging did not become ready')


def exercise(page, cdp, output, password, *, emulated=False):
    def touch(locator):
        if emulated:
            locator.tap()
            return
        locator.click(trial=True)  # Wait for a stable, unobstructed target; no click is sent.
        locator.scroll_into_view_if_needed()
        expect(locator).to_be_visible()
        box=locator.bounding_box()
        point={'x':box['x']+box['width']/2,'y':box['y']+box['height']/2}
        cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[point]})
        cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
    def tab(title):
        button=page.get_by_role('tab',name=title,exact=True)
        touch(button)
        expect(button).to_have_attribute('aria-selected','true')
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),title+' horizontal overflow'
    page.locator('.pcc-login input').fill(password)
    touch(page.get_by_role('button',name='Sign In',exact=True))
    expect(page.locator('.pcc-nav')).to_be_visible()
    assert 'Android' in page.evaluate('navigator.userAgent')
    assert page.evaluate('navigator.maxTouchPoints>0')
    assert page.evaluate("matchMedia('(hover:none)').matches")
    dashboard=page.locator('[data-panel=dashboard]')
    expect(dashboard.locator('.pcc-photo-tools')).to_have_css('opacity','1')
    expect(dashboard.locator('[data-photo-upload]')).to_be_visible()
    # set_input_files bypasses the chooser button: wait for the same readiness
    # a real user needs before sending its change event. Loading rejects uploads.
    expect(dashboard.locator('[data-photo-upload]')).to_be_enabled()
    photo=io.BytesIO();Image.new('RGB',(40,40),'#2a70af').save(photo,format='PNG')
    with page.expect_response(lambda response: urlsplit(response.url).path=='/api/account/photo' and response.request.method=='POST') as upload:
        dashboard.locator('[data-photo-file]').set_input_files({'name':'touch.png','mimeType':'image/png','buffer':photo.getvalue()})
    assert upload.value.status==200,f'Photo upload HTTP status: {upload.value.status}'
    expect(dashboard.locator('[data-profile-photo]')).to_be_visible()
    tab('Backup')
    backup=page.locator('[data-panel=backup]')
    expect(backup.locator('input[type=checkbox]')).to_have_count(13)
    touch(backup.locator('input[type=checkbox]').first)
    expect(backup.locator('.pcc-selected')).to_have_count(1)
    expect(backup.locator('[data-create]')).to_be_disabled()
    scroller=backup.locator('[data-archives]');scroller.scroll_into_view_if_needed()
    before=scroller.evaluate('e=>e.scrollTop')
    box=scroller.bounding_box()
    start={'x':box['x']+box['width']/2,'y':min(box['y']+box['height']-20,page.evaluate('innerHeight')-30)}
    cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[start]})
    for distance in (30,60,90,120,150):
        cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':start['x'],'y':start['y']-distance}]})
        page.wait_for_timeout(30)
    cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
    page.wait_for_function('(e)=>e.scrollTop>0',arg=scroller.element_handle())
    assert scroller.evaluate('e=>e.scrollTop')>before
    # A tap during kinetic scrolling may only stop the fling. Wait for actual
    # scrolling to settle before testing the next navigation action.
    page.wait_for_function('''e=>{const now=performance.now();if(e._pccTouchTop!==e.scrollTop){e._pccTouchTop=e.scrollTop;e._pccTouchChanged=now;return false;}return now-e._pccTouchChanged>250;}''',arg=scroller.element_handle())
    tab('Restore')
    restore=page.locator('[data-panel=restore]')
    expect(restore.locator('input[type=radio]')).to_have_count(13)
    touch(restore.locator('input[type=radio]').first)
    touch(restore.locator('[data-restore-action=validate]'))
    expect(restore.locator('[data-validation-notice]')).to_contain_text('not confirmed stopped')
    touch(restore.locator('[data-restore-action=cancel]'))
    expect(restore.locator('[data-restore-action=cancel]')).to_be_hidden()
    tab('History')
    history=page.locator('[data-panel=history]')
    expect(history.locator('.pcc-event-row')).not_to_have_count(0)
    touch(history.locator('input[type=checkbox]').first)
    touch(history.locator('[data-clear]'))
    expect(history.locator('dialog')).to_be_visible()
    touch(history.locator('[data-cancel]'))
    expect(history.locator('dialog')).to_be_hidden()
    tab('Settings')
    settings=page.locator('[data-panel=settings]')
    touch(settings.locator('[data-theme-choice=Dark]'))
    expect(page.locator('#pcc-app')).to_have_attribute('data-theme','dark')
    settings.locator('[data-language]').select_option('pl')
    expect(page.get_by_role('tab',name='Ustawienia',exact=True)).to_be_visible()
    for theme in ('Light','Dark'):
        tab('Ustawienia');touch(settings.locator(f'[data-theme-choice={theme}]'))
        expect(page.locator('#pcc-app')).to_have_attribute('data-theme',theme.lower())
        for index,title in enumerate(('Pulpit','Kopia zapasowa','Przywracanie','Historia','Ustawienia'),1):
            tab(title)
            page.screenshot(path=str(output/f'{theme.lower()}-{index}.png'),full_page=True)
    page.reload();expect(page.locator('.pcc-nav')).to_be_visible()
    expect(page.get_by_role('tab',name='Pulpit',exact=True)).to_be_visible()
    expect(page.locator('#pcc-app')).to_have_attribute('data-theme','dark')
    dashboard=page.locator('[data-panel=dashboard]')
    touch(dashboard.locator('[data-logout]'))
    expect(page.locator('.pcc-login')).to_be_visible()


def main():
    mode=os.environ.get('PCC_MOBILE_MODE','emulated')
    if mode not in ('emulated','android'):
        raise ValueError('PCC_MOBILE_MODE must be emulated or android')
    output=Path('dist/browser-screenshots')/('android-system' if mode=='android' else 'android-emulated')
    output.mkdir(parents=True,exist_ok=True)
    endpoint,adb=android_endpoint() if mode=='android' else (None,None)
    name='pcc-mobile-'+uuid.uuid4().hex[:12];volume=name+'-state'
    password='ci-touch-only-password';environment=dict(os.environ,PCC_BOOTSTRAP_VERIFIER=password_verifier(password))
    docker('volume','create',volume)
    page=None;browser=None;playwright=None;errors=[];network_errors=[]
    try:
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as transport:
            playwright=sync_playwright().start()
            temporary=Path(temporary);archives=temporary/'archives';fixtures(archives)
            docker('run','-d','--name',name,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true',
                '--tmpfs','/tmp:rw,noexec,nosuid,size=64m','-p','127.0.0.1::8443',
                '-v',volume+':/var/lib/plexconfigcontrol','-v',str(archives)+':/archives:ro',
                '-e','PCC_PUBLIC_HOST=127.0.0.1','-e','PCC_BOOTSTRAP_VERIFIER','-e','PCC_ARCHIVE_DIRECTORY=/archives',
                'plexconfigcontrol:test',env=environment)
            port=json.loads(docker('inspect',name))[0]['NetworkSettings']['Ports']['8443/tcp'][0]['HostPort']
            cert=temporary/'panel.crt'
            for _ in range(60):
                copied=subprocess.run(['docker','cp',name+':/var/lib/plexconfigcontrol/tls/panel.crt',str(cert)],capture_output=True)
                if copied.returncode==0:break
                time.sleep(.5)
            else:raise RuntimeError('No TLS identity')
            context=ssl.create_default_context(cafile=str(cert))
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
            for _ in range(60):
                try:
                    with opener.open(f'https://127.0.0.1:{port}/healthz',timeout=5) as response:
                        if response.status==200:break
                except OSError:pass
                time.sleep(.5)
            else:raise RuntimeError('HTTPS health probe failed')
            docker('exec',name,'python','-c',"from plexconfigcontrol.history import History; h=History('/var/lib/plexconfigcontrol'); [h.add('BACKUP','SUCCESS','CI touch fixture') for _ in range(20)]")
            if mode=='android':
                browser=playwright.chromium.connect_over_cdp(endpoint)
                context=browser.contexts[0]
                page=context.pages[0] if context.pages else context.new_page()
            else:
                browser=playwright.chromium.launch()
                context=browser.new_context(**playwright.devices['Pixel 5'],ignore_https_errors=True)
                page=context.new_page()
            page.set_default_timeout(15000)
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('response',lambda response:network_errors.append({'path':urlsplit(response.url).path,'method':response.request.method,'status':response.status}) if response.status>=400 and urlsplit(response.url).path.startswith('/api/') else None)
            page.on('requestfailed',lambda request:network_errors.append({'url':request.url,'failure':request.failure}))
            page.on('console',lambda message:network_errors.append({'console':message.text}) if message.type=='error' else None)
            cdp=context.new_cdp_session(page)
            # Only this disposable browser ignores its own synthetic CI cert.
            # The separate host-side health probe above verifies TLS normally.
            cdp.send('Security.setIgnoreCertificateErrors',{'ignore':True})
            # ADB loopback transport avoids depending on emulator Wi-Fi startup.
            # The tunnel is scoped to this fixture and removed even on failure.
            url=transport.enter_context(fixture_tunnel(adb,port)) if mode=='android' else f'https://127.0.0.1:{port}'
            page.goto(url)
            exercise(page,cdp,output,password,emulated=mode=='emulated')
            assert not errors,errors
            print(f'Mobile checks passed ({mode}); UA: '+page.evaluate('navigator.userAgent'))
            browser.close();page=None
    except BaseException:
        print('Mobile JavaScript errors:',errors)
        print('Mobile network/console errors:',network_errors)
        if page is not None:
            try:page.screenshot(path=str(output/'failure.png'),full_page=True)
            except Exception:pass
        subprocess.run(['docker','logs','--tail','30',name],check=False)
        raise
    finally:
        if playwright is not None:playwright.stop()
        subprocess.run(['docker','rm','-f',name],check=False,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','volume','rm',volume],check=False,stdout=subprocess.DEVNULL)


if __name__=='__main__':raise SystemExit(main())
