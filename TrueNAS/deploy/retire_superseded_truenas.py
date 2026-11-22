import json,subprocess
from pathlib import Path
def gh(*args):return subprocess.check_output(['gh',*args],text=True)
r=json.loads(gh('release','view','v1.6.2','--json','isDraft,assets'))
assert not r['isDraft']
a=next(a for a in r['assets'] if a['name']=='PlexConfigControl_TrueNAS_x86-64v1.6.2.zip')
assert a['size']>60000000
old=json.loads(gh('release','view','v1.6','--json','assets'))
assert any(a['name']=='PlexConfigControl_QuTShero_x86-64v1.6.qpkg' for a in old['assets'])
for name in ('PlexConfigControl_TrueNAS_x86-64v1.6.zip','SHA256SUMS'):
 if any(a['name']==name for a in old['assets']):gh('release','delete-asset','v1.6',name,'--yes')
try:gh('release','view','v1.6.1')
except subprocess.CalledProcessError:pass
else:gh('release','delete','v1.6.1','--yes','--cleanup-tag')
Path('/tmp/qnap-notes.md').write_text('''# PlexConfigControl 1.6 — QNAP QuTS hero x86-64

[Download the QNAP installer](https://github.com/ykrisw/PlexConfigControl/releases/download/v1.6/PlexConfigControl_QuTShero_x86-64v1.6.qpkg)

Back up, verify and restore Plex configuration on QNAP QuTS hero. Install the QPKG manually in App Center, open the application, sign in to QNAP and select the archive folder. Stop Plex manually before restoring.

MIT License, © 2026 Krzysztof Wojciechowski. Bundled dependencies retain their licenses, including GNU tar under GPLv3. [Source, licenses and instructions](https://github.com/ykrisw/PlexConfigControl/tree/main/QNAP).

Superseded TrueNAS installers have been removed. [Current TrueNAS 1.6.2](https://github.com/ykrisw/PlexConfigControl/releases/tag/v1.6.2).
''')
gh('release','edit','v1.6','--title','PlexConfigControl 1.6 — QNAP QuTS hero x86-64','--notes-file','/tmp/qnap-notes.md')
gh('release','edit','v1.6.2','--notes-file','TrueNAS/deploy/release-notes-1.6.2.md','--latest')
print('Superseded TrueNAS releases removed; QNAP installer and links retained.')
