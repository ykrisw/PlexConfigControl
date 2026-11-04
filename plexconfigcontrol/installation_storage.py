"""Installer storage gate: discover Plex before inspecting/creating output folders."""
from dataclasses import dataclass
from pathlib import Path
from .plex_storage import PlexStorage, StorageDiscoveryError, discover_plex_storage
from .storage import inspect_destination, create_destination


@dataclass(frozen=True)
class InstallationStoragePlan:
    parent: str
    plex: PlexStorage


def plan_storage(api, parent, *, manual_source=None):
    plex=discover_plex_storage(api,manual_source=manual_source)
    # Current emergency rollback operates on a whole dataset. Never silently
    # include unrelated data when Host Path points to a shared-dataset folder.
    if not plex.dedicated_dataset_root:
        raise StorageDiscoveryError('DEDICATED_PLEX_DATASET_REQUIRED')
    parent=str(Path(parent))
    inspect_destination(parent,forbidden_paths=(plex.source,'/mnt/TrueNAS/TrueNAS/PBS-Data'))
    return InstallationStoragePlan(parent,plex)


def create_storage(api, plan):
    if not isinstance(plan,InstallationStoragePlan):
        raise StorageDiscoveryError('INSTALLATION_STORAGE_PLAN_REQUIRED')
    # Read again immediately before the exclusive create. Discovery is not an
    # enduring grant of authority; the worker must recheck before each operation.
    if discover_plex_storage(api,manual_source=plan.plex.source if plan.plex.storage_type=='manual' else None)!=plan.plex:
        raise StorageDiscoveryError('PLEX_STORAGE_CHANGED')
    return create_destination(plan.parent,forbidden_paths=(plan.plex.source,'/mnt/TrueNAS/TrueNAS/PBS-Data'))


def manual_path_prompt(error, language='en'):
    """Installer form model; a failed auto-detection never removes manual entry."""
    if not isinstance(error,StorageDiscoveryError):
        raise TypeError('Expected a storage discovery failure')
    pl=language=='pl'
    return {
        'code':error.code,
        'manual_entry_available':True,
        'field':'manual_plex_config_path',
        'label':'Ścieżka konfiguracji Plex' if pl else 'Plex configuration path',
        'message':('Nie udało się potwierdzić lokalizacji konfiguracji Plex. Wpisz ścieżkę ręcznie i ponów sprawdzenie.' if pl else
                   'Plex configuration storage could not be confirmed. Enter its path manually and check again.'),
        'submit_label':'Sprawdź ścieżkę' if pl else 'Check path',
        'verification_required':True,
    }
