"""Verify actual selected POST names and both archive lists in the native QNAP UI."""
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'TrueNAS/tests'),str(Path(__file__).resolve().parents[2]/'TrueNAS')]
import execution_ui_e2e as execution
import mobile_archives_e2e as mobile
from playwright.sync_api import sync_playwright,expect
STATIC=Path(os.environ['PCC_STATIC']).resolve()
execution.STATIC=mobile.STATIC=STATIC
class Fixture(mobile.MobileFixture):
    def __init__(self,language,theme):
        super().__init__('backup',language,theme);self.validated=[]
    def handle(self,method,path,payload=None,query=''):
        if method=='POST' and path=='/api/restore/validate':
            self.validated.append(payload['archive'])
            self.operation.update(kind='RESTORE',phase='WAITING_FOR_PLEX_STOP',archive_identity='b'*64,
                validation_details={'archive':payload['archive'],'status':'VALID','sha256':'b'*64})
            return 202,{'accepted':True,'status_url':'/api/operation'}
        if method=='GET' and path=='/api/restore/readiness' and self.validated:
            return 200,{'ready':False,'archive':self.validated[-1],'reason':'STOP_PLEX_MANUALLY','plex':{'state':'RUNNING','available':True}}
        return super().handle(method,path,payload,query)
with sync_playwright() as p:
    browser=getattr(p,os.environ.get('PCC_TEST_BROWSER','chromium')).launch()
    for language in ('en','pl'):
        for theme in ('light','dark'):
            fixture=Fixture(language,theme)
            page=browser.new_page(viewport={'width':1920,'height':1080})
            page.route('**/*',fixture.route);page.goto(execution.ORIGIN)
            backup='Backup' if language=='en' else 'Kopia zapasowa'
            restore='Restore' if language=='en' else 'Przywracanie'
            page.get_by_role('tab',name=backup,exact=True).click()
            page.get_by_role('tab',name=restore,exact=True).click()
            expect(page.locator('[data-panel=restore] .pcc-archive-row')).to_have_count(1)
            new=dict(fixture.rows[0],name='PlexConfig_newest.tar.gz',inode='150')
            fixture.rows.append(new)
            page.get_by_role('tab',name=backup,exact=True).click();page.locator('[data-refresh]').click()
            expect(page.locator('[data-panel=restore] .pcc-archive-row')).to_have_count(2)
            page.get_by_role('tab',name=restore,exact=True).click()
            # User deleted all older archives; refresh must reconcile both lists.
            fixture.rows=[new];page.locator('[data-restore-action=refresh]').click()
            expect(page.locator('[data-panel=backup] .pcc-archive-row')).to_have_count(1)
            expect(page.locator('[data-panel=restore] .pcc-archive-row')).to_have_count(1)
            page.locator('input[name=restore-archive]').check()
            page.locator('[data-restore-action=validate]').click()
            page.wait_for_function("document.querySelector('[data-panel=restore] .pcc-archive-card').hidden")
            assert fixture.validated==[new['name']],fixture.validated
            page.close()
    browser.close()
print('Native QNAP lists refresh in both directions; validation POST contains the only selected newest archive: PASS')
