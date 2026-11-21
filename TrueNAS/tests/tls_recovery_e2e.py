"""Real browser: all panels remain accessible during API TLS failure and recover."""
import os
import execution_ui_e2e as execution
import mobile_archives_e2e as mobile
from playwright.sync_api import sync_playwright,expect

class Fixture(mobile.MobileFixture):
    failed=True
    def handle(self,method,path,payload=None,query=''):
        if method=='GET' and path=='/api/status' and self.failed:
            return 200,{'state':'UNKNOWN','available':False,'restore_allowed':False,'error_code':'TLS_UNTRUSTED'}
        return super().handle(method,path,payload,query)

with sync_playwright() as p:
    browser=getattr(p,os.environ.get('PCC_TEST_BROWSER','chromium')).launch()
    for language in ('pl','en'):
        for theme in ('light','dark'):
            fixture=Fixture('backup',language,theme)
            page=browser.new_page(viewport={'width':1280,'height':800})
            page.route('**/*',fixture.route);page.goto(execution.ORIGIN)
            for key,title in (('dashboard','Pulpit' if language=='pl' else 'Dashboard'),('backup','Kopia zapasowa' if language=='pl' else 'Backup'),('restore','Przywracanie' if language=='pl' else 'Restore')):
                page.get_by_role('tab',name=title,exact=True).click()
                notice=page.locator(f'[data-panel={key}] [data-api-connection-error]')
                expect(notice).to_be_visible()
                expect(notice).to_contain_text('CA')
            fixture.failed=False
            for key,title in (('dashboard','Pulpit' if language=='pl' else 'Dashboard'),('backup','Kopia zapasowa' if language=='pl' else 'Backup'),('restore','Przywracanie' if language=='pl' else 'Restore')):
                page.get_by_role('tab',name=title,exact=True).click()
                expect(page.locator(f'[data-panel={key}] [data-api-connection-error]')).to_be_hidden(timeout=10000)
                expect(page.locator(f'[data-panel={key}] [data-plex-state]')).to_have_attribute('data-plex-state','RUNNING')
            page.close()
    browser.close()
print('TLS diagnostics and reconnect in PL/EN, both themes, Dashboard/Backup/Restore: PASS')
