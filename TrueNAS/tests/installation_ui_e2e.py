"""Actual installer component with an intercepted adapter, never NAS writes."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from plexconfigcontrol.installation_flow import InstallationStorageFlow

STATIC=Path(__file__).resolve().parents[1]/'plexconfigcontrol/static'
ORIGIN='https://pcc-installation-ui.invalid'


def exercise(browser,output,language,theme,width,*,uncertain):
    from playwright.sync_api import expect
    # No API calls: construction returns only the trusted field descriptions.
    initial=InstallationStorageFlow(None,language).view()
    context=browser.new_context(viewport={'width':width,'height':1000},color_scheme='dark' if theme!='light' else 'light',service_workers='block')
    page=context.new_page();page.set_default_timeout(12000);errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def route(request):
        url=urlsplit(request.request.url)
        if url.scheme+'://'+url.netloc!=ORIGIN:request.abort();return
        if url.path.startswith('/assets/'):
            name=url.path.removeprefix('/assets/');path=STATIC/name
            if Path(name).name!=name or path.suffix not in ('.css','.mjs') or not path.is_file():request.abort();return
            request.fulfill(content_type='text/css' if path.suffix=='.css' else 'text/javascript',body=path.read_text());return
        if url.path!='/':request.abort();return
        html='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
        <link rel="stylesheet" href="/assets/panel-layout.css"><link rel="stylesheet" href="/assets/panel-app.css"><link rel="stylesheet" href="/assets/installation-view.css"></head>
        <body><div class="pcc-shell" data-theme="THEME"><section id="installer"></section></div>
        <script type="module">
        import {mountInstallationView} from '/assets/installation-view.mjs';
        import {installationPreview} from '/assets/installation-controller.mjs';
        window.calls={checks:[],creates:[]};let saved;const initial=INITIAL;
        const client={async check(inputs){window.calls.checks.push(inputs);
            if(window.calls.checks.length===1)return {phase:'MANUAL_REQUIRED',error:{message:'Manual path required'}};
            saved={phase:'READY',can_create:true,revision:'a'.repeat(32),storage:{type:'manual',source:'<img src=x onerror=alert(1)>',dataset:'tank/plex',
                output:installationPreview(inputs).folder,folder_name:inputs.folder_name||'Plex Backup',archive_prefix:inputs.archive_prefix||'PlexConfig',logs_folder:'Logs'}};return saved;
        },async create(payload){window.calls.creates.push(payload);if(UNCERTAIN)throw Error('Lost response');
            return {...saved,phase:'COMPLETE',revision:null,can_create:false};}};
        window.disposeInstaller=mountInstallationView(document.getElementById('installer'),client,{initial,language:'LANGUAGE'});
        </script></body></html>'''.replace('THEME',theme).replace('INITIAL',json.dumps(initial)).replace('LANGUAGE',language).replace('UNCERTAIN','true' if uncertain else 'false')
        request.fulfill(content_type='text/html',body=html)
    page.route('**/*',route)
    try:
        page.goto(ORIGIN)
        parent=page.locator('input[name=parent]');expect(parent).to_have_accessible_name('Miejsce przechowywania kopii zapasowych Plex' if language=='pl' else 'Plex backup storage location');parent.fill('/mnt/Archive/Backups')
        page.locator('input[name=folder_name]').fill('Moje kopie')
        page.locator('input[name=archive_prefix]').fill('Dupa')
        expect(page.locator('[data-preview-paths]')).to_contain_text('/mnt/Archive/Backups/Moje kopie/Logs')
        assert page.evaluate('window.calls.checks.length')==0
        page.locator('[data-install-check]').click();expect(page.locator('[data-manual-source]')).to_be_visible()
        page.locator('[data-manual-source]').fill('/mnt/apps/plex')
        page.locator('[data-install-check]').click();expect(page.locator('[data-install-create]')).to_be_enabled()
        assert page.locator('[data-install-source] img').count()==0  # source is text, never HTML
        page.locator('[data-install-create]').click();expect(page.locator('dialog[open]')).to_be_visible()
        expect(page.locator('[data-confirm-paths]')).to_contain_text('/mnt/Archive/Backups/Moje kopie')
        page.screenshot(path=str(output/f'confirm-{language}-{theme}-{width}.png'),full_page=True)
        page.locator('[data-install-cancel]').click();assert page.evaluate('window.calls.creates.length')==0
        parent.fill('/mnt/SecondPool')
        expect(page.locator('[data-install-create]')).to_be_disabled()
        expect(page.locator('[data-preview-paths]')).to_contain_text('/mnt/SecondPool/Moje kopie')
        page.locator('[data-install-check]').click();expect(page.locator('[data-install-create]')).to_be_enabled()
        page.locator('[data-install-create]').click();page.locator('[data-install-confirm]').click()
        expect(page.locator('dialog')).not_to_be_visible()
        expect(page.locator('[data-install-status]')).to_contain_text(('Nie udało się potwierdzić' if language=='pl' else 'could not be confirmed') if uncertain else ('zostało skonfigurowane' if language=='pl' else 'storage configured'))
        expect(page.locator('[data-install-check]')).to_be_disabled();expect(parent).to_be_disabled()
        assert page.evaluate('window.calls.creates.length')==1
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        if theme=='light':expect(page.locator('h2')).to_have_css('color','rgb(0, 0, 0)')
        assert not errors,errors
        page.screenshot(path=str(output/f'result-{language}-{theme}-{width}.png'),full_page=True)
    except BaseException:
        try:page.screenshot(path=str(output/f'failure-{language}-{theme}-{width}.png'),full_page=True)
        except Exception:pass
        print('Installer UI errors:',errors,flush=True)
        raise
    finally:context.close()


def main():
    from playwright.sync_api import sync_playwright
    engine=os.environ.get('PCC_TEST_BROWSER','chromium')
    if engine not in ('chromium','firefox','msedge'):raise ValueError('Unsupported fixture browser')
    output=Path('dist/browser-screenshots')/engine/'installation-ui';output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='msedge') if engine=='msedge' else getattr(playwright,engine).launch()
        try:
            print('Installer browser:',engine,browser.version,flush=True)
            for language,theme,width in [('en','light',900),('pl','dark',900),('en','system',390),('pl','light',390)]:
                exercise(browser,output,language,theme,width,uncertain=theme=='dark')
            print('Installer component PASS (intercepted adapter; no host/folder operations)',flush=True)
        finally:browser.close()


if __name__=='__main__':main()
