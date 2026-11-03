"""Real browser checks on disposable Docker fixtures, never the user's NAS."""
import io
import json
import os
import ssl
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright,expect
from plexconfigcontrol.archives import REQUIRED
from plexconfigcontrol.installation import password_verifier
from container_smoke import docker


def fixtures(directory):
    directory.mkdir()
    for day in range(1,14):
        with tarfile.open(directory/f'TrueNASPlexConfig_2026.10.{day:02d}_10.30.00.tar.gz','w:gz') as archive:
            for name in REQUIRED:
                member=tarfile.TarInfo(name);member.size=4
                archive.addfile(member,io.BytesIO(b'test'))


def main():
    output=Path('dist/browser-screenshots');output.mkdir(parents=True,exist_ok=True)
    name='pcc-browser-'+uuid.uuid4().hex[:12];volume=name+'-state'
    password='ci-browser-only-password';environment=dict(os.environ,PCC_BOOTSTRAP_VERIFIER=password_verifier(password))
    docker('volume','create',volume)
    page=None;playwright=None;errors=[]
    try:
        with tempfile.TemporaryDirectory() as temporary:
            temporary=Path(temporary);archives=temporary/'archives';fixtures(archives)
            docker('run','-d','--name',name,'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges:true',
                '--tmpfs','/tmp:rw,noexec,nosuid,size=64m','-p','127.0.0.1::8443',
                '-v',volume+':/var/lib/plexconfigcontrol','-v',str(archives)+':/archives:ro',
                '-e','PCC_PUBLIC_HOST=127.0.0.1','-e','PCC_BOOTSTRAP_VERIFIER','-e','PCC_ARCHIVE_DIRECTORY=/archives',
                'plexconfigcontrol:test',env=environment)
            port=int(json.loads(docker('inspect',name))[0]['NetworkSettings']['Ports']['8443/tcp'][0]['HostPort'])
            cert=temporary/'panel.crt'
            for _ in range(60):
                copied=subprocess.run(['docker','cp',name+':/var/lib/plexconfigcontrol/tls/panel.crt',str(cert)],capture_output=True)
                if copied.returncode==0:break
                time.sleep(.5)
            else:raise RuntimeError('No TLS identity')
            context=ssl.create_default_context(cafile=str(cert))
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
            base=f'https://127.0.0.1:{port}'
            for _ in range(60):
                try:
                    with opener.open(base+'/healthz',timeout=5) as response:
                        if response.status==200:break
                except OSError:pass
                time.sleep(.5)
            else:raise RuntimeError('HTTPS health probe failed')
            # Synthetic history is created only inside this disposable CI volume.
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.history import History; h=History('/var/lib/plexconfigcontrol'); "
                "[h.add('BACKUP' if i%2 else 'RESTORE','FAILED' if i%4==0 else 'SUCCESS','CI fixture event '+str(i)) for i in range(20)]")
            playwright=sync_playwright().start()
            browser=playwright.chromium.launch()
            # Only this ephemeral browser accepts its own CI self-signed cert.
            # The health probe above verifies that certificate normally.
            context=browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':1080},color_scheme='light')
            page=context.new_page();page.set_default_timeout(12000)
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base);page.locator('.pcc-login input').fill(password)
            page.get_by_role('button',name='Sign In',exact=True).click()
            expect(page.locator('.pcc-nav')).to_be_visible()
            dashboard=page.locator('[data-panel=dashboard]')
            expect(dashboard.locator('[data-account-active]')).to_have_text('ACTIVE')
            expect(dashboard.locator('[data-photo-upload]')).to_be_enabled()
            expect(dashboard.locator('.pcc-photo-tools')).to_have_css('opacity','0')
            dashboard.locator('.pcc-avatar').hover()
            expect(dashboard.locator('.pcc-photo-tools')).to_have_css('opacity','1')
            photo=io.BytesIO();Image.new('RGB',(48,36),'#2a70af').save(photo,format='PNG')
            dashboard.locator('[data-photo-file]').set_input_files({'name':'ci-photo.png','mimeType':'image/png','buffer':photo.getvalue()})
            expect(dashboard.locator('[data-profile-photo]')).to_be_visible()
            expect(dashboard.locator('[data-profile-photo]')).to_have_js_property('naturalWidth',512)
            page.mouse.move(10,10)
            page.get_by_role('tab',name='Backup',exact=True).click()
            backup=page.locator('[data-panel=backup]')
            expect(backup.locator('.pcc-archive-row')).to_have_count(13)
            expect(backup.locator('[data-create]')).to_be_disabled()
            backup.locator('input[type=checkbox]').first.check()
            expect(backup.locator('.pcc-selected')).to_have_count(1)
            expect(backup.locator('[data-delete]')).to_be_disabled()
            assert backup.locator('[data-archives]').evaluate('(e)=>e.scrollHeight>e.clientHeight')
            page.get_by_role('tab',name='Restore',exact=True).click()
            restore=page.locator('[data-panel=restore]')
            expect(restore.locator('input[type=radio]')).to_have_count(13)
            assert restore.locator('input:checked').count()==0
            restore.locator('input[type=radio]').first.check()
            expect(restore.locator('[data-restore-action=validate]')).to_be_enabled()
            restore.locator('[data-restore-action=validate]').click()
            expect(restore.locator('[data-validation-notice]')).to_contain_text('not confirmed stopped')
            expect(restore.locator('[data-restore-action=validate]')).to_be_disabled()
            restore.locator('[data-restore-action=cancel]').click()
            expect(restore.locator('[data-restore-action=cancel]')).to_be_hidden()
            page.get_by_role('tab',name='History',exact=True).click()
            history=page.locator('[data-panel=history]')
            expect(history.locator('.pcc-event-row')).not_to_have_count(0)
            assert history.locator('[data-events]').evaluate('(e)=>e.scrollHeight>e.clientHeight')
            history.locator('input[type=checkbox]').first.check()
            with page.expect_download() as downloaded:
                history.locator('[data-download]').click()
            assert downloaded.value.suggested_filename.endswith('.log')
            history.locator('[data-clear]').click()
            expect(history.locator('dialog')).to_be_visible()
            history.locator('[data-cancel]').click()
            page.get_by_role('tab',name='Settings',exact=True).click()
            settings=page.locator('[data-panel=settings]')
            settings.locator('[data-theme-choice=Dark]').click()
            expect(page.locator('#pcc-app')).to_have_attribute('data-theme','dark')
            settings.locator('[data-language]').select_option('pl')
            expect(page.get_by_role('tab',name='Ustawienia',exact=True)).to_be_visible()
            expect(settings.locator('[data-about]')).to_have_text('O aplikacji')
            settings.locator('[data-theme-choice=Light]').click()
            expect(page.locator('#pcc-app')).to_have_attribute('data-theme','light')
            for theme in ('Light','Dark'):
                page.get_by_role('tab',name='Ustawienia',exact=True).click()
                settings.locator(f'[data-theme-choice={theme}]').click()
                expect(page.locator('#pcc-app')).to_have_attribute('data-theme',theme.lower())
                heights=[]
                for index,title in enumerate(('Pulpit','Kopia zapasowa','Przywracanie','Historia','Ustawienia'),1):
                    page.get_by_role('tab',name=title,exact=True).click()
                    visible=page.locator('.pcc-page:visible');expect(visible).to_be_visible()
                    page.mouse.move(10,10)
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),f'{title} overflows horizontally'
                    heights.append(visible.bounding_box()['height'])
                    page.screenshot(path=str(output/f'{theme.lower()}-{index}.png'),full_page=True)
                assert max(heights)-min(heights)<2,f'Unequal panel heights: {heights}'
            for width in (360,320):
                page.set_viewport_size({'width':width,'height':900})
                for title in ('Pulpit','Kopia zapasowa','Przywracanie','Historia','Ustawienia'):
                    page.get_by_role('tab',name=title,exact=True).click()
                    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth'),f'{title} overflows at {width}px'
                    assert page.locator('.pcc-nav').evaluate("e=>[...e.querySelectorAll('button')].every(b=>{const s=b.querySelector('span').getBoundingClientRect(),r=b.getBoundingClientRect();return s.left>=r.left-1&&s.right<=r.right+1;})"),f'Tab labels overlap at {width}px'
                page.screenshot(path=str(output/f'mobile-{width}.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1080})
            page.get_by_role('tab',name='Pulpit',exact=True).click()
            dashboard=page.locator('[data-panel=dashboard]')
            dashboard.locator('.pcc-avatar').hover();dashboard.locator('[data-photo-remove]').click()
            dashboard.locator('[data-photo-confirm]').click()
            expect(dashboard.locator('[data-profile-photo]')).to_be_hidden()
            page.reload();expect(page.locator('.pcc-nav')).to_be_visible()
            expect(page.locator('#pcc-app')).to_have_attribute('data-theme','dark')
            dashboard=page.locator('[data-panel=dashboard]')
            dashboard.locator('[data-password]').click()
            dashboard.locator('input[name=current]').fill(password)
            dashboard.locator('input[name=password]').fill('ci-new-password')
            dashboard.locator('input[name=confirmation]').fill('ci-new-password')
            dashboard.locator('[data-save]').click()
            expect(page.locator('.pcc-login')).to_be_visible()
            page.locator('.pcc-login input').fill('ci-new-password')
            page.get_by_role('button',name='Sign In',exact=True).click()
            expect(page.locator('.pcc-nav')).to_be_visible()
            page.locator('[data-panel=dashboard] [data-logout]').click()
            expect(page.locator('.pcc-login')).to_be_visible()
            assert not errors,f'Browser errors: {errors}'
            browser.close();page=None
        print('Real Chromium UI checks passed: five panels, themes, Polish, profile, validation, history and account.')
        return 0
    except BaseException:
        print('Browser JavaScript errors:',errors)
        if page is not None:
            try:page.screenshot(path=str(output/'failure.png'),full_page=True)
            except Exception:pass
        subprocess.run(['docker','logs','--tail','50',name],check=False)
        raise
    finally:
        if playwright is not None: playwright.stop()
        subprocess.run(['docker','rm','-f',name],check=False,stdout=subprocess.DEVNULL)
        subprocess.run(['docker','volume','rm',volume],check=False,stdout=subprocess.DEVNULL)


if __name__=='__main__':raise SystemExit(main())
