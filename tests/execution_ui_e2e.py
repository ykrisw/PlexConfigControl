"""Native UI checks against an in-memory API fixture; no Docker/NAS operations.

All browser HTTP requests are intercepted. No product runtime privilege or write
capability is enabled. Screenshots belong only to this disposable UI fixture.
"""
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

STATIC = Path(__file__).resolve().parents[1]/'plexconfigcontrol/static'
ORIGIN = 'https://pcc-execution-ui.invalid'
NAME = 'TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz'


class FixtureAPI:
    def __init__(self, panel, language, theme):
        self.panel, self.language, self.theme = panel, language, theme
        self.plex = 'RUNNING'
        self.rows = [{'name':NAME,'size':'42','device':'1','inode':'9223372036854775931',
                      'modified_ns':'1793664000000000123'}]
        self.operation = {'phase':'IDLE','kind':None,'snapshot_id':None,'outcome':None,
                          'execution_request_id':None}
        self.progress = None
        self.current = None
        self.jobs, self.payloads, self.posts = {}, {}, []
        self.executions = 0
        self.lose_reply = False
        self.hide_current = False

    def receipt(self, payload, kind):
        identifier = payload['request_id']
        if identifier in self.payloads:
            if self.payloads[identifier] != payload:
                return 409, {'error':'Conflicting request identity'}
        else:
            self.payloads[identifier] = json.loads(json.dumps(payload))
            self.executions += 1
            self.current = {'request_id':identifier,'kind':kind,'state':'RUNNING',
                            'created_ns':'1793664000000000001','updated_ns':'1793664000000000002'}
            self.jobs[identifier] = self.current
            self.operation.update(kind=kind,phase='RUNNING',execution_request_id=identifier,
                outcome={'code':kind+'_IN_PROGRESS','archive':NAME})
            self.progress = {'operation':kind,'stage':'RESTORING' if kind=='RESTORE' else 'CREATING_ARCHIVE',
                             'active':True,'finished':None,'elapsed_seconds':2}
        self.hide_current = False
        return 202, {'accepted':True,'request_id':identifier,'kind':kind,'status_url':'/api/operation'}

    def complete(self):
        self.current['state'] = 'SUCCEEDED'
        kind = self.current['kind']
        self.operation.update(phase='SUCCESS',outcome={'code':kind+'_COMPLETED','archive':NAME})
        self.progress.update(stage='COMPLETED',active=False,finished=123)

    def handle(self, method, path, payload=None, query=''):
        if method == 'GET':
            if path == '/api/archives': return 200, self.rows
            if path == '/api/capabilities':
                return 200, {'backup_create':True,'backup_overwrite':True,'restore_execute':True,
                             'archive_delete':False,'snapshot_management':False,'archive_validation':True}
            if path == '/api/status': return 200, {'state':self.plex,'available':True}
            if path == '/api/operation':
                if self.hide_current: return 503, {'error':'Fixture operation read temporarily unavailable'}
                return 200, {'operation':self.operation,'progress':self.progress,
                    'publication':{'status':'NONE','pending':False,'archive':None,'temporary_file':None},
                    'execution':self.current,'execution_bound':self.current is not None and
                    self.operation['execution_request_id']==self.current['request_id']}
            if path == '/api/backup/plan':
                if self.operation['phase']=='RUNNING': return 409, {'error':'Operation active'}
                return 200, {'archive_count':len(self.rows),
                    'action':'ASK_OVERWRITE_OR_NEW' if len(self.rows)==1 else 'CREATE_NEW',
                    'existing_archive':self.rows[0] if len(self.rows)==1 else None,'overwrite_available':True}
            if path == '/api/restore/readiness':
                return 200, {'ready':self.plex=='STOPPED','archive':NAME,
                    'reason':None if self.plex=='STOPPED' else 'STOP_PLEX_MANUALLY',
                    'plex':{'state':self.plex,'available':True}}
            if path == '/api/execution/status':
                job=self.jobs.get(parse_qs(query).get('request_id',[''])[0])
                if job is not None: self.hide_current=False
                return 200, {'found':job is not None,'execution':job}
        if method == 'POST':
            if path == '/api/restore/validate':
                self.operation.update(kind='RESTORE',phase='WAITING_FOR_PLEX_STOP',
                    archive_identity='b'*64,validation_details={'archive':NAME,'status':'VALID','sha256':'b'*64})
                return 202, {'accepted':True,'status_url':'/api/operation'}
            if path in ('/api/backup/start','/api/restore/execute'):
                self.posts.append(json.loads(json.dumps(payload)))
                return self.receipt(payload,'BACKUP' if path=='/api/backup/start' else 'RESTORE')
        return 404, {'error':'No such fixture route'}

    def route(self, route):
        request=route.request;url=urlsplit(request.url)
        if url.scheme+'://'+url.netloc != ORIGIN:
            route.abort();return
        if url.path.startswith('/assets/'):
            name=url.path.removeprefix('/assets/')
            if Path(name).name!=name or Path(name).suffix not in ('.css','.mjs'):
                route.abort();return
            path=STATIC/name
            if not path.is_file():
                route.fulfill(status=404,body='Missing fixture asset');return
            route.fulfill(content_type='text/css' if path.suffix=='.css' else 'text/javascript',body=path.read_text());return
        if url.path=='/':
            mount='mountBackupView' if self.panel=='backup' else 'mountRestoreView'
            module='backup-view' if self.panel=='backup' else 'restore-view'
            html=f'''<!doctype html><html lang="{self.language}"><head><meta name="viewport" content="width=device-width,initial-scale=1">
                <link rel="stylesheet" href="/assets/panel-layout.css"><link rel="stylesheet" href="/assets/panel-app.css"></head>
                <body><div class="pcc-shell" data-theme="{self.theme}"><main class="pcc-main"><section id="fixture" class="pcc-page" data-panel="{self.panel}" data-theme="{self.theme}"></section></main></div>
                <script type="module">import {{PanelClient}} from '/assets/panel-client.mjs';
                import {{{mount}}} from '/assets/{module}.mjs';const client=new PanelClient();client.csrf='fixture-only-csrf';
                window.disposeFixture={mount}(document.getElementById('fixture'),client,{{language:'{self.language}'}});</script></body></html>'''
            route.fulfill(content_type='text/html',body=html);return
        payload=None
        if request.method=='POST':
            if request.headers.get('x-csrf-token')!='fixture-only-csrf':
                route.fulfill(status=403,json={'error':'Fixture CSRF missing'});return
            payload=request.post_data_json
        status,body=self.handle(request.method,url.path,payload,url.query)
        if request.method=='POST' and url.path in ('/api/backup/start','/api/restore/execute') and self.lose_reply:
            # Keep the latest-status read unavailable until explicit lookup/retry;
            # otherwise normal polling correctly resolves this lost reply first.
            self.lose_reply=False;self.hide_current=True;route.abort('failed');return
        route.fulfill(status=status,json=body)


def check_dialog(page, dialog, theme):
    from playwright.sync_api import expect
    expect(dialog).to_be_visible()
    expect(dialog).to_have_css('border-top-width','3px')
    expect(dialog).to_have_css('border-top-color','rgb(229, 179, 33)')
    assert dialog.evaluate('''element=>{const sample=document.createElement('div');
        sample.style.background='var(--pcc-bg)';element.append(sample);
        const expected=getComputedStyle(sample).backgroundColor;sample.remove();
        return getComputedStyle(element).backgroundColor===expected;}''')
    if theme=='light': expect(dialog.locator('h3')).to_have_css('color','rgb(0, 0, 0)')
    box=dialog.bounding_box();assert box and box['x']>=0 and box['x']+box['width']<=page.viewport_size['width']+1
    assert dialog.evaluate('(element)=>element.scrollWidth<=element.clientWidth+1')


def backup_case(browser, output, language, theme, width, *, check_only=False):
    from playwright.sync_api import expect
    fixture=FixtureAPI('backup',language,theme);fixture.lose_reply=True
    context=browser.new_context(viewport={'width':width,'height':1100},color_scheme='dark' if theme!='light' else 'light',service_workers='block')
    page=context.new_page();page.set_default_timeout(12000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.route('**/*',fixture.route)
    try:
        page.goto(ORIGIN)
        create=page.locator('[data-create]');expect(create).to_be_enabled();create.click()
        dialog=page.locator('[data-backup-dialog]');check_dialog(page,dialog,theme)
        expect(dialog.locator('[data-backup-archive]')).to_have_text(NAME)
        expect(dialog.locator('[data-backup-another]')).to_have_text('Utwórz kolejną kopię' if language=='pl' else 'Create Another Copy')
        page.screenshot(path=str(output/f'backup-choice-{language}-{theme}-{width}.png'),full_page=True)
        dialog.locator('[data-backup-overwrite]').click()
        expect(dialog).to_be_hidden();expect(page.locator('[data-submission-retry]')).to_be_visible()
        assert len(fixture.posts)==1 and fixture.executions==1
        if check_only:
            page.locator('[data-submission-check]').click()
            expect(page.locator('[data-submission-retry]')).to_be_hidden()
            assert len(fixture.posts)==1
        else:
            page.locator('[data-submission-retry]').click()
            expect(page.locator('[data-submission-retry]')).to_be_hidden()
            assert len(fixture.posts)==2 and fixture.posts[0]==fixture.posts[1]
            assert fixture.posts[0]['archive']['inode']=='9223372036854775931'
            assert fixture.executions==1
        fixture.complete()
        expect(page.locator('[data-operation-result]')).to_contain_text('zakończył się sukcesem' if language=='pl' else 'completed successfully')
        assert not errors, errors
    except BaseException:
        try: page.screenshot(path=str(output/f'failure-{fixture.panel}-{language}-{theme}-{width}.png'),full_page=True)
        except Exception: pass
        if errors: print('Fixture page errors:',errors,flush=True)
        raise
    finally: context.close()


def restore_case(browser, output, language, theme, width):
    from playwright.sync_api import expect
    fixture=FixtureAPI('restore',language,theme)
    context=browser.new_context(viewport={'width':width,'height':1100},color_scheme='dark' if theme!='light' else 'light',service_workers='block')
    page=context.new_page();page.set_default_timeout(12000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.route('**/*',fixture.route)
    try:
        page.goto(ORIGIN);page.locator('input[type=radio]').first.check()
        page.locator('[data-restore-action=validate]').click()
        expect(page.locator('[data-validation-notice]')).to_contain_text('ręcznie' if language=='pl' else 'manually')
        execute=page.locator('[data-restore-execute]');expect(execute).to_be_disabled();assert not fixture.posts
        fixture.plex='STOPPED';page.locator('[data-restore-action=refresh]').click();expect(execute).to_be_enabled();execute.click()
        dialog=page.locator('[data-restore-dialog]');check_dialog(page,dialog,theme)
        typed=dialog.locator('[data-confirm-restore]');confirm=dialog.locator('[data-restore-dialog-confirm]')
        typed.fill('restore');expect(confirm).to_be_disabled();typed.fill('RESTORE');expect(confirm).to_be_enabled()
        page.screenshot(path=str(output/f'restore-confirm-{language}-{theme}-{width}.png'),full_page=True)
        fixture.operation['archive_identity']='c'*64;fixture.operation['validation_details']['sha256']='c'*64
        expect(confirm).to_be_disabled()  # Poll detects a changed validation checkpoint.
        dialog.locator('[data-restore-dialog-cancel]').click();execute.click()
        typed.fill('RESTORE');confirm.click();expect(dialog).to_be_hidden()
        assert len(fixture.posts)==1 and fixture.posts[0]['sha256']=='c'*64
        assert fixture.posts[0]['confirmation']=='RESTORE'
        expect(page.locator('[data-restore-action=validate]')).to_be_disabled()
        expect(page.locator('input[type=radio]').first).to_be_disabled()
        fixture.complete()
        expect(page.locator('[data-operation-result]')).to_contain_text('zakończyło się sukcesem' if language=='pl' else 'completed successfully')
        assert fixture.plex=='STOPPED' and fixture.executions==1 and not errors, errors
    except BaseException:
        try: page.screenshot(path=str(output/f'failure-{fixture.panel}-{language}-{theme}-{width}.png'),full_page=True)
        except Exception: pass
        if errors: print('Fixture page errors:',errors,flush=True)
        raise
    finally: context.close()


def main():
    from playwright.sync_api import sync_playwright
    engine=os.environ.get('PCC_TEST_BROWSER','chromium')
    if engine not in ('chromium','firefox','msedge'):raise ValueError('Unsupported fixture browser')
    output=Path('dist/browser-screenshots')/engine/'execution-ui';output.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(channel='msedge') if engine=='msedge' else getattr(playwright,engine).launch()
        try:
            print(f'Execution UI browser: {engine} {browser.version}',flush=True)
            for language,theme,width in (('en','light',900),('pl','dark',900),('en','system',390),('pl','light',390)):
                backup_case(browser,output,language,theme,width)
                restore_case(browser,output,language,theme,width)
            backup_case(browser,output,'en','light',900,check_only=True)
            print('Execution dialogs: PASS (intercepted API only; no host execution)',flush=True)
        finally:browser.close()


if __name__=='__main__':main()
