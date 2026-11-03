"""Real browser checks on disposable Docker fixtures, never the user's NAS."""
import io
import json
import os
import shutil
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
    engine=os.environ.get('PCC_TEST_BROWSER','chromium')
    if engine not in ('chromium','firefox','msedge'):
        raise ValueError('PCC_TEST_BROWSER must be chromium, firefox or msedge')
    output=Path('dist/browser-screenshots')/engine;output.mkdir(parents=True,exist_ok=True)
    name='pcc-browser-'+uuid.uuid4().hex[:12];volume=name+'-state'
    password='ci-browser-only-password';environment=dict(os.environ,PCC_BOOTSTRAP_VERIFIER=password_verifier(password))
    docker('volume','create',volume)
    page=None;playwright=None;errors=[];network_errors=[]
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
            browser=playwright.chromium.launch(channel='msedge') if engine=='msedge' else getattr(playwright,engine).launch()
            print(f'Browser under test: {engine} {browser.version}')
            # Only this ephemeral browser accepts its own CI self-signed cert.
            # The health probe above verifies that certificate normally.
            context=browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':1080},color_scheme='light')
            page=context.new_page();page.set_default_timeout(12000)
            if engine=='msedge': assert 'Edg/' in page.evaluate('navigator.userAgent'),'Microsoft Edge channel was not launched'
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('requestfailed',lambda request:network_errors.append({'url':request.url,'failure':request.failure}))
            page.on('console',lambda message:network_errors.append({'console':message.text}) if message.type=='error' else None)
            if engine!='firefox':
                # Only this disposable browser accepts this fixture's generated
                # certificate. The host-side health probe verifies it above.
                context.new_cdp_session(page).send('Security.setIgnoreCertificateErrors',{'ignore':True})
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
            # Import while the panel is already open. Copy only archive bytes;
            # there is deliberately no matching history event or app manifest.
            imported_name='TrueNASPlexConfig_2026.09.30_08.15.00.tar.gz'
            external=temporary/imported_name
            shutil.copyfile(archives/'TrueNASPlexConfig_2026.10.13_10.30.00.tar.gz',external)
            imported=archives/imported_name
            shutil.copyfile(external,imported)
            backup.locator('[data-refresh]').click()
            expect(backup.locator('.pcc-archive-row')).to_have_count(14)
            expect(backup.locator('[data-count]')).to_have_text('14 backups')
            imported_checkbox=backup.get_by_role('checkbox',name='Select: '+imported_name,exact=True)
            imported_checkbox.check()
            expect(imported_checkbox).to_be_checked()
            expect(backup.locator('.pcc-selected').filter(has_text=imported_name)).to_have_count(1)
            imported_checkbox.uncheck()
            page.get_by_role('tab',name='Restore',exact=True).click()
            restore=page.locator('[data-panel=restore]')
            expect(restore.locator('input[type=radio]')).to_have_count(14)
            assert restore.locator('input:checked').count()==0
            # The same open Restore tab must discover removal and return.
            imported.unlink()
            restore.locator('[data-restore-action=refresh]').click()
            expect(restore.locator('input[type=radio]')).to_have_count(13)
            shutil.copyfile(external,imported)
            restore.locator('[data-restore-action=refresh]').click()
            expect(restore.locator('input[type=radio]')).to_have_count(14)
            imported_radio=restore.get_by_role('radio',name='Select: '+imported_name,exact=True)
            imported_radio.check()
            expect(imported_radio).to_be_checked()
            expect(restore.locator('.pcc-selected')).to_contain_text(imported_name)
            expect(restore.locator('[data-restore-action=validate]')).to_be_enabled()
            restore.locator('[data-restore-action=validate]').click()
            expect(restore.locator('[data-validation-notice]')).to_contain_text('not confirmed stopped')
            expect(restore.locator('[data-restore-action=validate]')).to_be_disabled()
            restore.locator('[data-restore-action=cancel]').click()
            expect(restore.locator('[data-restore-action=cancel]')).to_be_hidden()
            # Return to the approved 13-row screenshot fixture after the import
            # check. Only this disposable test file is removed, never NAS data.
            imported.unlink()
            restore.locator('[data-restore-action=refresh]').click()
            expect(restore.locator('input[type=radio]')).to_have_count(13)
            expect(restore.locator('input:checked')).to_have_count(0)
            page.get_by_role('tab',name='History',exact=True).click()
            history=page.locator('[data-panel=history]')
            expect(history.locator('.pcc-event-row')).not_to_have_count(0)
            assert history.locator('[data-events]').evaluate('(e)=>e.scrollHeight>e.clientHeight')
            imported_event=history.locator('.pcc-event-row').filter(has_text='Archive detected').filter(has_text=imported_name).first
            expect(imported_event).to_be_visible()
            expect(imported_event.locator('[data-status=INFO]')).to_have_text('INFO')
            imported_event.locator('input[type=checkbox]').check()
            with page.expect_download() as import_download:
                history.locator('[data-download]').click()
            import_log=temporary/'import-event.log'
            import_download.value.save_as(str(import_log))
            assert imported_name in import_log.read_text() and 'NOT VALIDATED' in import_log.read_text()
            imported_event.locator('input[type=checkbox]').uncheck()
            history.locator('input[type=checkbox]').first.check()
            with page.expect_download() as downloaded:
                history.locator('[data-download]').click()
            assert downloaded.value.suggested_filename.endswith('.log')
            history.locator('[data-clear]').click()
            expect(history.locator('dialog')).to_be_visible()
            history.locator('[data-cancel]').click()
            # Synthetic retained intent only: no snapshot is created on a NAS.
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.state import StateStore; from plexconfigcontrol.operations import Phase; "
                "s=StateStore('/var/lib/plexconfigcontrol'); "
                "ctx=s.transaction(); op=ctx.__enter__(); op.phase=Phase.RECOVERY_REQUIRED; "
                "op.kind='BACKUP'; op.snapshot_id='test/config@pcc-backup-'+'a'*32; ctx.__exit__(None,None,None)")
            for tab_name,panel in (('Backup',backup),('Restore',restore)):
                page.get_by_role('tab',name=tab_name,exact=True).click()
                recovery=panel.locator('[data-recovery]')
                expect(recovery).to_be_visible()
                expect(recovery.locator('[data-recovery-title]')).to_have_text('Recovery required')
                expect(recovery.locator('[data-recovery-status]')).to_contain_text('could not be confirmed')
                expect(recovery.locator('[data-recovery-limit]')).to_contain_text('removal is unavailable')
                recovery.locator('[data-recovery-refresh]').click()
                expect(recovery.locator('[data-recovery-status]')).to_contain_text('could not be confirmed')
                assert recovery.locator('button').count()==1
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.state import StateStore; from plexconfigcontrol.operations import Phase; "
                "s=StateStore('/var/lib/plexconfigcontrol'); ctx=s.transaction(); op=ctx.__enter__(); "
                "op.phase=Phase.FAILED; op.snapshot_id=None; ctx.__exit__(None,None,None)")
            expect(restore.locator('[data-recovery]')).to_be_hidden()
            # A FAILED checkpoint with a durable publication marker still blocks
            # new work. Reload must show only diagnostic names, never validity.
            recovery_archive='TrueNASPlexConfig_2026.10.13_10.30.00.tar.gz'
            recovery_old='TrueNASPlexConfig_2026.10.12_10.30.00.tar.gz'
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.publication_intent import record_replacement; "
                "record_replacement('/var/lib/plexconfigcontrol','.pcc-'+'a'*32+'.tmp',"
                +repr(recovery_archive)+",'b'*64,"+repr(recovery_old)+","
                "dict(device=0,inode=0,size=0,modified_ns=0,changed_ns=0))")
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.state import StateStore; s=StateStore('/var/lib/plexconfigcontrol'); "
                "ctx=s.transaction(); op=ctx.__enter__(); "
                "op.outcome={'code':'BACKUP_PUBLISHED_REVIEW','archive':"+repr(recovery_archive)+"}; ctx.__exit__(None,None,None)")
            page.reload();expect(page.locator('.pcc-nav')).to_be_visible()
            page.set_viewport_size({'width':360,'height':900})
            for tab_name,panel_key in (('Backup','backup'),('Restore','restore')):
                page.get_by_role('tab',name=tab_name,exact=True).click()
                panel=page.locator(f'[data-panel={panel_key}]')
                recovery=panel.locator('[data-recovery]')
                expect(recovery.locator('[data-recovery-publication]')).to_be_visible()
                expect(recovery.locator('[data-publication-archive]')).to_contain_text(recovery_archive)
                expect(recovery.locator('[data-publication-older]')).to_contain_text(recovery_old)
                expect(recovery.locator('[data-publication-stage]')).to_contain_text('presence not checked')
                expect(recovery.locator('[data-publication-warning]')).to_contain_text('not proof')
                expect(recovery.locator('[data-recovery-outcome]')).to_contain_text('not a successful Backup')
                assert recovery.locator('button').count()==1
                if panel_key=='backup':
                    expect(panel.locator('[data-create]')).to_be_disabled()
                    expect(panel.locator('[data-delete]')).to_be_disabled()
                else:
                    expect(panel.locator('[data-restore-action=validate]')).to_be_disabled()
                    expect(panel.locator('input[name=restore-archive]').first).to_be_disabled()
                assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
                page.screenshot(path=str(output/f'recovery-publication-{panel_key}.png'),full_page=True)
            # Only the disposable CI fixture is reset; there is no web mutation.
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.publication_intent import clear_replacement; "
                "clear_replacement('/var/lib/plexconfigcontrol')")
            expect(page.locator('[data-panel=restore] [data-recovery]')).to_be_hidden()
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.state import StateStore; s=StateStore('/var/lib/plexconfigcontrol'); "
                "ctx=s.transaction(); op=ctx.__enter__(); "
                "op.outcome={'code':'BACKUP_FAILED','archive':"+repr(recovery_archive)+"}; ctx.__exit__(None,None,None)")
            page.get_by_role('tab',name='Backup',exact=True).click()
            expect(page.locator('[data-panel=backup] [data-operation-result]')).to_contain_text('No new archive has been confirmed')
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            page.screenshot(path=str(output/'backup-failed-result.png'),full_page=True)
            page.reload();expect(page.locator('.pcc-nav')).to_be_visible()
            page.get_by_role('tab',name='Backup',exact=True).click()
            expect(page.locator('[data-panel=backup] [data-operation-result]')).to_contain_text('Backup failed')
            # Synthetic historical rollback result: do not infer current snapshot
            # presence or create any snapshot/Restore on a host.
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.state import StateStore; from plexconfigcontrol.operations import Phase; "
                "s=StateStore('/var/lib/plexconfigcontrol'); ctx=s.transaction(); op=ctx.__enter__(); "
                "op.kind='RESTORE'; op.phase=Phase.RECOVERY_REQUIRED; op.snapshot_id='test/config@pcc-restore-'+'c'*32; "
                "op.outcome={'code':'RESTORE_ROLLBACK_VERIFIED','archive':"+repr(recovery_archive)+"}; ctx.__exit__(None,None,None)")
            page.get_by_role('tab',name='Restore',exact=True).click()
            restore_recovery=page.locator('[data-panel=restore] [data-recovery]')
            expect(restore_recovery.locator('[data-recovery-outcome]')).to_contain_text('Restore remains FAILED')
            expect(restore_recovery.locator('[data-recovery-status]')).to_contain_text('could not be confirmed')
            page.screenshot(path=str(output/'restore-rollback-verified.png'),full_page=True)
            page.reload();expect(page.locator('.pcc-nav')).to_be_visible()
            page.get_by_role('tab',name='Restore',exact=True).click()
            expect(restore_recovery.locator('[data-recovery-outcome]')).to_contain_text('Restore remains FAILED')
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.state import StateStore; s=StateStore('/var/lib/plexconfigcontrol'); "
                "ctx=s.transaction(); op=ctx.__enter__(); "
                "op.outcome={'code':'RESTORE_RECOVERY_UNCONFIRMED','archive':"+repr(recovery_archive)+"}; ctx.__exit__(None,None,None)")
            expect(restore_recovery.locator('[data-recovery-outcome]')).to_contain_text('Recovery could not be verified')
            page.screenshot(path=str(output/'restore-recovery-unconfirmed.png'),full_page=True)
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.state import StateStore; from plexconfigcontrol.operations import Phase; "
                "s=StateStore('/var/lib/plexconfigcontrol'); ctx=s.transaction(); op=ctx.__enter__(); "
                "op.kind='BACKUP'; op.phase=Phase.FAILED; op.snapshot_id=None; "
                "op.outcome={'code':'BACKUP_FAILED','archive':"+repr(recovery_archive)+"}; ctx.__exit__(None,None,None)")
            expect(restore_recovery).to_be_hidden()
            page.set_viewport_size({'width':1440,'height':1080})
            page.get_by_role('tab',name='Settings',exact=True).click()
            settings=page.locator('[data-panel=settings]')
            diagnostic_requests=[]
            page.on('request',lambda request:diagnostic_requests.append(request.method) if request.url.endswith('/api/integration') else None)
            expect(settings.locator('[data-integration-check]')).to_be_hidden()
            settings.locator('[data-details-label]').click()
            expect(settings.locator('[data-integration-check]')).to_be_visible()
            assert diagnostic_requests==[], 'Opening Details must not start host probes'
            settings.locator('[data-integration-check]').click()
            expect(settings.locator('[data-integration-checks]')).to_contain_text('Archive list read verified; count: 13')
            expect(settings.locator('[data-integration-limit]')).to_contain_text('do not enable')
            assert diagnostic_requests==['GET']
            page.set_viewport_size({'width':360,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            page.screenshot(path=str(output/'settings-connection-checks.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1080})
            settings.locator('[data-details-label]').click()
            settings.locator('[data-theme-choice=Dark]').click()
            expect(page.locator('#pcc-app')).to_have_attribute('data-theme','dark')
            settings.locator('[data-language]').select_option('pl')
            expect(page.get_by_role('tab',name='Ustawienia',exact=True)).to_be_visible()
            expect(settings.locator('[data-about]')).to_have_text('O aplikacji')
            settings.locator('[data-details-label]').click()
            expect(settings.locator('[data-integration-title]')).to_have_text('Sprawdzanie połączenia')
            expect(settings.locator('[data-integration-checks]')).to_contain_text('liczba: 13')
            assert diagnostic_requests==['GET'], 'Changing language must not run diagnostics again'
            settings.locator('[data-details-label]').click()
            page.get_by_role('tab',name='Kopia zapasowa',exact=True).click()
            expect(page.locator('[data-panel=backup] [data-operation-result]')).to_contain_text('Nie potwierdzono utworzenia nowego archiwum')
            docker('exec',name,'python','-c',
                "from plexconfigcontrol.state import StateStore; s=StateStore('/var/lib/plexconfigcontrol'); "
                "ctx=s.transaction(); op=ctx.__enter__(); op.outcome=None; ctx.__exit__(None,None,None)")
            expect(page.locator('[data-panel=backup] [data-operation-result]')).to_be_hidden()
            page.get_by_role('tab',name='Ustawienia',exact=True).click()
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
                    assert page.locator('.pcc-nav').evaluate("e=>{const y=[...e.querySelectorAll('button svg')].map(s=>s.getBoundingClientRect().top);return Math.max(...y)-Math.min(...y)<2;}"),f'Navigation icons are uneven at {width}px'
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
            # A second authenticated browser context must lose its old session
            # after password change, independently of the initiating page.
            other_context=browser.new_context(ignore_https_errors=True)
            other_page=other_context.new_page();other_page.set_default_timeout(12000)
            if engine!='firefox':
                other_context.new_cdp_session(other_page).send('Security.setIgnoreCertificateErrors',{'ignore':True})
            other_page.goto(base)
            other_page.locator('.pcc-login input').fill(password)
            other_page.get_by_role('button',name='Sign In',exact=True).click()
            expect(other_page.locator('.pcc-nav')).to_be_visible()
            dashboard.locator('[data-password]').click()
            dashboard.locator('input[name=current]').fill(password)
            dashboard.locator('input[name=password]').fill('ci-new-password')
            dashboard.locator('input[name=confirmation]').fill('ci-new-password')
            dashboard.locator('[data-save]').click()
            expect(page.locator('.pcc-login')).to_be_visible()
            other_page.reload();expect(other_page.locator('.pcc-login')).to_be_visible()
            other_context.close()
            page.locator('.pcc-login input').fill('ci-new-password')
            page.get_by_role('button',name='Sign In',exact=True).click()
            expect(page.locator('.pcc-nav')).to_be_visible()
            page.locator('[data-panel=dashboard] [data-logout]').click()
            expect(page.locator('.pcc-login')).to_be_visible()
            assert not errors,f'Browser errors: {errors}'
            browser.close();page=None
        print(f'Real {engine} UI checks passed: five panels, themes, Polish, profile, validation, history and account.')
        return 0
    except BaseException:
        print('Browser JavaScript errors:',errors)
        print('Browser network/console errors:',network_errors)
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
