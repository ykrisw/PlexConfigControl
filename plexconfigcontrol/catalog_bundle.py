"""Produce one version directory for the TrueNAS Apps catalog."""
import json
import re
from pathlib import Path


APP = 'plexconfigcontrol'
_FIELDS = {
    'panel': ('host_ip', 'host_port', 'verifier_file'),
    'backup': ('archive_parent', 'folder_name', 'archive_prefix'),
    'connection': ('api_url', 'api_user', 'api_key_file', 'api_ca_file'),
    'plex': ('storage_mode',),
}


def catalog_files(template_root, deployment, plan, values, version):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('A catalog version such as 0.1.0 is required')
    root = Path(template_root)
    questions = json.loads((root/'questions.yaml').read_text(encoding='utf-8'))
    reviewed = {group: {field: values[group][field] for field in fields
                        if field in values[group]} for group, fields in _FIELDS.items()}
    reviewed['connection']['api_url'] = reviewed['connection'].get('api_url') or ''
    reviewed['plex'].setdefault('storage_mode', 'automatic')
    if reviewed['plex']['storage_mode'] == 'manual':
        reviewed['plex']['manual_source'] = values['plex']['manual_source']
    for group in questions['questions']:
        for field in group['schema']['attrs']:
            name = field['variable']
            if name in reviewed.get(group['variable'], {}):
                field['schema']['default'] = reviewed[group['variable']][name]

    compose = deployment.compose()
    services = compose['services']
    panel_state = services['panel']['volumes'][0]
    for service in services.values():
        service['depends_on'] = {'initialize-state': {'condition': 'service_completed_successfully'}}
    services['initialize-state'] = {
        'image': deployment.panel_image, 'pull_policy': 'never',
        'user': '0:0', 'restart': 'no', 'read_only': True,
        'cap_drop': ['ALL'], 'cap_add': ['CHOWN', 'DAC_OVERRIDE', 'FOWNER'],
        'security_opt': ['no-new-privileges:true'], 'network_mode': 'none',
        'healthcheck': {'disable': True},
        'entrypoint': ['python', '-m', 'plexconfigcontrol.catalog_init'],
        'command': ['--folder', plan.naming.folder_name, '--prefix', plan.naming.archive_prefix],
        'volumes': [panel_state],
    }
    metadata = {
        'name': APP, 'title': 'PlexConfigControl', 'version': version, 'app_version': version,
        'description': 'Kopie zapasowe i przywracanie konfiguracji Plex Media Server.',
        'annotations': {'min_scale_version': '25.10.8'},
        'categories': ['backup'], 'keywords': ['plex', 'backup', 'restore'], 'train': 'community',
        'home': 'https://github.com/ykrisw/PlexConfigControl',
        'sources': ['https://github.com/ykrisw/PlexConfigControl'],
        'lib_version': '2.3.18',
    }
    # Changing these two form values cannot redirect a verified host mount.
    reviewed['panel'].pop('host_port')
    reviewed['backup'].pop('archive_prefix')
    definition = {'pcc_release': {'app_name': APP, 'state': deployment.state,
                                  'reviewed_fields': reviewed, 'compose': compose}}
    def serialize(value):
        return json.dumps(value, indent=2, ensure_ascii=False) + '\n'
    return {
        'app.yaml': serialize(metadata),
        'questions.yaml': serialize(questions),
        'ix_values.yaml': serialize(definition),
        'templates/docker-compose.yaml': (root/'templates/docker-compose.yaml').read_text(encoding='utf-8'),
    }
