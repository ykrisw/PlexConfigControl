"""Preview the real shell and verify shared refresh, typography and desktop motion."""
import json
import os
from pathlib import Path
import execution_ui_e2e as execution
import mobile_archives_e2e as mobile
from playwright.sync_api import sync_playwright, expect

static = os.environ.get('PCC_STATIC')
if static:
    execution.STATIC = mobile.STATIC = Path(static).resolve()
output = Path('dist/visual-preview') / os.environ.get('PCC_PLATFORM', 'truenas')
output.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    browser = getattr(p, os.environ.get('PCC_TEST_BROWSER', 'chromium')).launch()
    for language in ('en', 'pl'):
        for theme in ('dark', 'light'):
            fixture = mobile.MobileFixture('backup', language, theme)
            page = browser.new_page(viewport={'width':1740, 'height':900}, color_scheme=theme)
            page.route('**/*', fixture.route)
            page.goto(execution.ORIGIN)
            backup = 'Backup' if language == 'en' else 'Kopia zapasowa'
            restore = 'Restore' if language == 'en' else 'Przywracanie'
            page.get_by_role('tab', name=backup, exact=True).click()
            expect(page.locator('[data-panel=backup] .pcc-archive-row')).to_have_count(1)
            page.get_by_role('tab', name=restore, exact=True).click()
            expect(page.locator('[data-panel=restore] .pcc-archive-row')).to_have_count(1)
            styles = page.evaluate("""() => {const title=document.querySelector('.pcc-validation-heading h2'), help=document.querySelector('.pcc-validation-heading p'), logo=document.querySelector('.pcc-logo'); const style = el => {const s=getComputedStyle(el);return [s.fontFamily,s.fontSize,s.fontWeight,s.lineHeight]};return {title:style(title), help:style(help), logo:{width:logo.getBoundingClientRect().width,height:logo.getBoundingClientRect().height}}}""")
            assert styles['title'] == styles['help'], styles
            assert styles['logo'] == {'width':24, 'height':24}, styles
            extra = dict(fixture.rows[0], name='PlexConfig_New.tar.gz', inode='50')
            fixture.rows.append(extra)
            page.locator('[data-restore-action=refresh]').click()
            expect(page.locator('[data-panel=restore] .pcc-archive-row')).to_have_count(2)
            expect(page.locator('[data-panel=backup] .pcc-archive-row')).to_have_count(2)
            page.get_by_role('tab', name=backup, exact=True).click()
            fixture.rows = [extra]
            page.locator('[data-refresh]').click()
            expect(page.locator('[data-panel=backup] .pcc-archive-row')).to_have_count(1)
            expect(page.locator('[data-panel=restore] .pcc-archive-row')).to_have_count(1)
            assert 'PlexConfig_New.tar.gz' in page.locator('[data-panel=restore] [data-archive-list]').text_content()
            page.get_by_role('tab', name=restore, exact=True).click()
            page.screenshot(path=str(output/f'restore-{language}-{theme}.png'), clip={'x':0,'y':0,'width':1740,'height':560})
            # Indeterminate animation is visual only; real measured values remain native.
            page.evaluate("""() => {const meter=document.querySelector('[data-panel=restore] .pcc-stage-progress');meter.hidden=false;meter.closest('.pcc-operation-workspace').hidden=false;}""")
            assert page.locator('[data-panel=restore] .pcc-stage-progress').evaluate("el=>getComputedStyle(el,'::after').animationDuration") == '3s'
            page.set_viewport_size({'width':390,'height':844})
            assert page.locator('[data-panel=restore] .pcc-stage-progress').evaluate("el=>getComputedStyle(el,'::after').content") == 'none'
            page.close()
    browser.close()
print('Shared refresh both directions, EN/PL, dark/light, identical typography, 20% logo and desktop-only motion: PASS')
