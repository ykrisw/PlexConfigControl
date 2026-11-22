"""Create App Center metadata using QNAP's public plugins/item feed format."""
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
from xml.etree import ElementTree as ET

DESCRIPTION = {
    'en': 'Back up and restore your Plex configuration with full data verification. For QNAP QuTS hero x86_64.',
    'pl': 'Kopie zapasowe i przywracanie konfiguracji Plexa z weryfikacją danych. Dla QNAP QuTS hero x86_64.',
}
BASE = 'https://github.com/ykrisw/PlexConfigControl/releases/download/qnap-v1.6.3/'


def make(package, output, language):
    package = Path(package)
    root = ET.Element('plugins')
    ET.SubElement(root, 'cachechk').text = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    item = ET.SubElement(root, 'item')
    fields = {
        'name': 'PlexConfigControl', 'internalName': 'PCC', 'category': 'Backup/Sync',
        'description': DESCRIPTION[language], 'developer': 'Krzysztof Wojciechowski',
        'developerLink': 'https://github.com/ykrisw/PlexConfigControl',
        'maintainer': 'Krzysztof Wojciechowski', 'version': '1.6.3',
        'icon80': BASE + 'PlexConfigControl_80.png', 'icon100': BASE + 'PlexConfigControl_80.png',
        'type': 'Backup/Sync', 'language': 'English, Polski',
        'publishedDate': datetime.now(timezone.utc).strftime('%Y/%m/%d'), 'volumeSelect': '1',
    }
    for key, value in fields.items():
        ET.SubElement(item, key).text = value
    platform = ET.SubElement(item, 'platform')
    ET.SubElement(platform, 'platformID').text = 'TS-NASX86'
    ET.SubElement(platform, 'location').text = BASE + package.name
    ET.SubElement(platform, 'md5').text = hashlib.md5(package.read_bytes()).hexdigest()
    ET.indent(root)
    ET.ElementTree(root).write(output, encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    make(sys.argv[1], sys.argv[2], sys.argv[3])
