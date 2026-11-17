"""Verify the staged QNAP frontend with the real NAS sign-in dialog, using fake HTTP only."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import execution_ui_e2e as execution
import mobile_archives_e2e as mobile
from playwright.sync_api import sync_playwright, expect

STATIC = Path(os.environ['PCC_STATIC']).resolve()
execution.STATIC = mobile.STATIC = STATIC
source = STATIC.parents[1]
spec = importlib.util.spec_from_file_location('plexconfigcontrol.qnap_notice_backend_fixture', source/'plexconfigcontrol/qnap_web.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for signed_in in (False,True):
    client = Mock()
    client.request.return_value = {'authenticated':signed_in,'location':None,'recovery_required':False}
    app = module.QnapWeb(SimpleNamespace(sessions=SimpleNamespace(authenticated=lambda token:True)),client)
    response = json.loads(b''.join(app({'PATH_INFO':'/api/capabilities','REQUEST_METHOD':'GET'}, lambda *args:None)))
    assert response['qnap_authenticated'] is signed_in
    assert response['backup_create'] is False


class Fixture(mobile.MobileFixture):
    def __init__(self, language, theme):
        super().__init__('backup', language, theme)
        self.signed_in = False
        self.reject = False

    def route(self, route):
        path = urlsplit(route.request.url).path
        if path == '/':
            body = (STATIC/'index.html').read_text().replace('</head>', '<link rel="stylesheet" href="/assets/qnap-tools.css"><script type="module" src="/assets/qnap-tools.mjs"></script></head>')
            route.fulfill(content_type='text/html; charset=utf-8',body=body)
        elif path == '/api/capabilities':
            value = self.handle('GET',path)[1]
            value.update(qnap_authenticated=self.signed_in,backup_create=False,restore_execute=False)
            route.fulfill(json=value)
        elif path == '/api/qnap/info':
            route.fulfill(json={'authenticated':self.signed_in,'location':None,'busy':False,'recovery_required':False})
        elif path == '/api/qnap/auth':
            if self.reject:
                route.fulfill(status=409,json={'error':'Fixture NAS sign-in rejected'})
            else:
                self.signed_in=True
                route.fulfill(json={'authenticated':True})
        else:
            super().route(route)


def sign_in(page, language):
    page.get_by_role('tab',name='Dashboard' if language=='en' else 'Pulpit',exact=True).click()
    page.locator('[data-qnap-control][data-auth]').click()
    dialog=page.locator('.pcc-qnap-dialog')
    dialog.locator('[name=username]').fill('fixture-user')
    dialog.locator('[name=password]').fill('fixture-password-only')
    dialog.locator('[type=submit]').click()
    return dialog


engine=os.environ.get('PCC_TEST_BROWSER','chromium')
with sync_playwright() as p:
    browser=getattr(p,engine).launch()
    for language in ('en','pl'):
        for theme in ('light','dark'):
            fixture=Fixture(language,theme)
            page=browser.new_page(viewport={'width':1280,'height':850},color_scheme=theme)
            page.route('**/*',fixture.route)
            page.goto(execution.ORIGIN)
            backup='Backup' if language=='en' else 'Kopia zapasowa'
            page.get_by_role('tab',name=backup,exact=True).click()
            notice=page.locator('[data-backup-unavailable]')
            message='Sign in to QNAP before creating a backup.' if language=='en' else 'Zaloguj się na Qnap przed utworzeniem kopii zapasowej'
            expect(notice).to_have_text(message)
            expect(notice).to_be_visible()
            expect(page.locator('[data-create]')).to_be_disabled()
            sign_in(page,language)
            # Backup remains unavailable without a destination, but the signed-in notice must vanish.
            expect(notice).to_have_text('')
            expect(notice).to_have_attribute('hidden','')
            page.get_by_role('tab',name=backup,exact=True).click()
            expect(notice).to_be_hidden()
            expect(page.locator('[data-create]')).to_be_disabled()
            fixture.signed_in=False
            page.locator('[data-refresh]').click()
            expect(notice).to_have_text(message)
            expect(notice).to_be_visible()
            fixture.reject=True
            dialog=sign_in(page,language)
            expect(dialog.locator('[role=alert]')).to_have_text('Fixture NAS sign-in rejected')
            expect(notice).to_have_text(message)
            dialog.locator('[data-cancel]').click()
            page.get_by_role('tab',name=backup,exact=True).click()
            expect(notice).to_be_visible()
            page.close()
    browser.close()
print('QNAP sign-in prompt, successful sign-in removal, missing destination, expired session and rejected sign-in: PASS ('+engine+')')
