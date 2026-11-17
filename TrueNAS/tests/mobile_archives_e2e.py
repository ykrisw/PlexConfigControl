"""Check native page scrolling and archive space using the full application shell."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from execution_ui_e2e import FixtureAPI, ORIGIN, STATIC


class MobileFixture(FixtureAPI):
    def route(self, route):
        path = urlsplit(route.request.url).path
        if path == '/':
            route.fulfill(content_type='text/html; charset=utf-8', body=(STATIC/'index.html').read_bytes())
        elif path == '/api/session':
            route.fulfill(json={'authenticated': True, 'csrf': 'fixture-only-csrf'})
        elif path == '/api/settings':
            route.fulfill(json={'language': self.language, 'theme': self.theme.title(), 'timezone': 'Europe/London'})
        elif path == '/api/account/photo/status':
            route.fulfill(json={'exists': False, 'revision': None})
        elif path == '/api/history':
            route.fulfill(json=[{'id': index, 'kind': 'BACKUP', 'status': 'SUCCESS',
                'created': '2026-11-11T00:00:00Z', 'archive': self.rows[0]['name']}
                for index in range(1, 41)])
        else:
            super().route(route)


def main():
    from playwright.sync_api import sync_playwright, expect
    engine = os.environ.get('PCC_TEST_BROWSER', 'chromium')
    output = Path('dist/browser-screenshots')/engine/'mobile-archives'
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = getattr(playwright, engine).launch()
        try:
            for language in ('pl', 'en'):
                for theme in ('light', 'dark'):
                    for width, height in ((320, 568), (390, 700), (390, 844), (430, 932)):
                        fixture = MobileFixture('backup', language, theme)
                        fixture.rows *= 8
                        context = browser.new_context(viewport={'width': width, 'height': height},
                            color_scheme=theme, has_touch=True, service_workers='block')
                        page = context.new_page()
                        page.route('**/*', fixture.route)
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        try:
                            page.goto(ORIGIN)
                            page.get_by_role('tab', name='Kopia zapasowa' if language=='pl' else 'Backup', exact=True).click()
                            expect(page.locator('[data-create]')).to_be_enabled()
                            expect(page.locator('[data-execution-note]')).to_have_count(0)
                            refresh = page.locator('.pcc-archives [data-refresh]').bounding_box()
                            delete = page.locator('.pcc-archives [data-delete]').bounding_box()
                            assert abs(refresh['height']-44) < 1 and abs(refresh['height']-delete['height']) < 1
                            positions = []
                            for panel, title in (('backup', 'Kopia zapasowa' if language=='pl' else 'Backup'),
                                                 ('restore', 'Przywracanie' if language=='pl' else 'Restore')):
                                page.get_by_role('tab', name=title, exact=True).click()
                                expect(page.locator(f'[data-panel={panel}] .pcc-plex')).to_be_visible()
                                page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
                                page.wait_for_timeout(80)
                                strip = page.locator(f'.pcc-page[data-panel={panel}]>.pcc-plex').bounding_box()
                                positions.append(strip['y'])
                                if height>=700:
                                    assert -21 <= strip['y'] <= -19, (engine, language, theme, width, height, panel, strip)
                                else:
                                    assert strip['y']<=-19, (panel, strip)
                                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                                listing = page.locator(f'.pcc-page[data-panel={panel}] .pcc-scroll-frame').bounding_box()
                                assert listing['height'] >= 128, (panel, listing)
                                if width==390 and height==844:
                                    page.screenshot(path=str(output/f'{panel}-{language}-{theme}.png'))
                            assert abs(positions[0]-positions[1]) < 1, positions
                            page.get_by_role('tab', name='Historia' if language=='pl' else 'History', exact=True).click()
                            expect(page.locator('[data-events] .pcc-event-row')).to_have_count(40)
                            page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
                            page.wait_for_timeout(80)
                            stats = page.locator('.pcc-history-stats').bounding_box()
                            assert abs(stats['y']-positions[0]) < 1, (engine, language, theme, width, height, stats, positions)
                            listing = page.locator('.pcc-history .pcc-scroll-frame').bounding_box()
                            assert listing['height']>=128
                            assert page.locator('[data-events]').evaluate('(list)=>list.scrollHeight>list.clientHeight')
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                            if width==390 and height==844:
                                page.screenshot(path=str(output/f'history-{language}-{theme}.png'))
                            assert not errors, errors
                        finally:
                            context.close()
            print('Full mobile shell: matched Backup/Restore/History scrolling and usable lists: PASS')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
