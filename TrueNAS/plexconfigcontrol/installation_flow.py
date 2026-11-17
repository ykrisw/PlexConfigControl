"""Trusted installer controller, not a WWW endpoint or host-execution grant."""
import secrets
from datetime import datetime, timezone
from .archives import archive_name
from pathlib import Path, PurePosixPath
from threading import RLock

from .installation_storage import plan_storage, create_storage, manual_path_prompt
from .plex_storage import StorageDiscoveryError
from .naming import InvalidNaming, Naming, save_naming
from .storage import describe_setup_error, RenameRequired, SetupIncomplete, DestinationChanged


class InstallationStorageFlow:
    """Explicit check -> exact plan confirmation -> single creation attempt.

    The deployment owns this controller and its API client. No browser can supply
    an API method/dataset or promote a discovery result into execution authority.
    """
    def __init__(self, api, language='en', *, state_directory=None):
        self._api=api
        self._state_directory=state_directory
        self._language='pl' if language=='pl' else 'en'
        self._lock=RLock()
        self._plan=None
        self._destination=None
        self._view={'phase':'UNVERIFIED','revision':None,'can_create':False,
                    'manual_entry_available':True,'error':None,'storage':None,
                    'fields':installation_fields(self._language),'preview':None}

    def view(self):
        import copy
        with self._lock:return copy.deepcopy(self._view)

    def _inputs(self, parent, folder_name, archive_prefix):
        values={'parent':parent,'folder_name':'Plex Backup' if folder_name in (None,'') else folder_name,
                'archive_prefix':'PlexConfig' if archive_prefix in (None,'') else archive_prefix}
        for field in self._view['fields']:
            if field['name'] in values:
                value=values[field['name']]
                field['value']=value if isinstance(value,str) else ''
        try:self._view['preview']=installation_preview(parent,folder_name=folder_name,archive_prefix=archive_prefix,language=self._language)
        except (ValueError,TypeError):self._view['preview']=None

    def edit(self, parent, *, folder_name=None, archive_prefix=None):
        """Host-free form input update; immediately invalidates an older check."""
        with self._lock:
            if self._view['phase'] in ('COMPLETE','REVIEW_REQUIRED'):return self.view()
            self._plan=None
            self._view.update(phase='UNVERIFIED',revision=None,can_create=False,error=None,storage=None)
            self._inputs(parent,folder_name,archive_prefix)
            return self.view()

    def check(self, parent, *, manual_source=None, folder_name=None, archive_prefix=None):
        with self._lock:
            if self._view['phase'] in ('COMPLETE','REVIEW_REQUIRED'):
                return self.view()
            # Any fresh check invalidates the previous revision, even on failure.
            self._plan=None
            self._view.update(phase='UNVERIFIED',revision=None,can_create=False,error=None,storage=None)
            self._inputs(parent,folder_name,archive_prefix)
            try:
                plan=plan_storage(self._api,parent,manual_source=manual_source,folder_name=folder_name,archive_prefix=archive_prefix)
            except InvalidNaming:
                message=('Podaj poprawną nazwę folderu i początek nazwy archiwum. Prefiks: 1–64 litery A–Z, cyfry, _ lub -; bez ścieżek.' if self._language=='pl' else 'Enter a valid folder name and archive prefix. Prefix: 1–64 ASCII letters, digits, _ or -; no paths.')
                self._view.update(phase='UNVERIFIED',error={'code':'INVALID_NAMING','message':message})
                return self.view()
            except StorageDiscoveryError as error:
                prompt=manual_path_prompt(error,self._language)
                messages={
                    'SETTINGS_MOUNT_MISMATCH':('The entered/configured path does not match Plex /config. Correct it and check again.','Wpisana lub skonfigurowana ścieżka nie odpowiada /config Plexa. Popraw ją i sprawdź ponownie.'),
                    'DEDICATED_PLEX_DATASET_REQUIRED':('This folder shares a dataset. Current Restore requires a separate dataset for Plex configuration.','Ten folder współdzieli dataset. Obecne Przywracanie wymaga osobnego datasetu konfiguracji Plex.'),
                    'PROTECTED_STORAGE':('This protected location cannot be used. Select another location.','Nie można użyć tej chronionej lokalizacji. Wybierz inną.'),
                }
                if error.code in messages:prompt['message']=messages[error.code][self._language=='pl']
                self._view.update(phase='MANUAL_REQUIRED',error=prompt)
                return self.view()
            except Exception as error:
                safe=describe_setup_error(error,self._language)
                self._view.update(phase='RENAME_REQUIRED' if isinstance(error,RenameRequired) else 'UNVERIFIED',error=safe)
                return self.view()
            self._plan=plan
            if self._view['preview'] is not None:self._view['preview']['checked']=True
            self._view.update(phase='READY',revision=secrets.token_hex(16),can_create=True,
                storage={'type':plan.plex.storage_type,'source':plan.plex.source,'dataset':plan.plex.dataset,
                         'output':str(Path(plan.parent)/plan.naming.folder_name),'folder_name':plan.naming.folder_name,'archive_prefix':plan.naming.archive_prefix,'logs_folder':'Logs'})
            return self.view()

    def create(self, revision, *, confirmed=False):
        with self._lock:
            if self._view['phase'] in ('COMPLETE','REVIEW_REQUIRED'):
                return self.view()
            if (confirmed is not True or self._view['phase']!='READY' or self._plan is None
                    or not isinstance(revision,str) or revision!=self._view['revision']):
                return self.view()  # No write for stale/unconfirmed plans.
            plan=self._plan
            if plan.naming!=Naming() and self._state_directory is None:
                self._view.update(error={'code':'INSTALLATION_STATE_REQUIRED','message':('Brak prywatnego miejsca zapisu ustawień instalacji.' if self._language=='pl' else 'Private installation settings storage is required.')})
                return self.view()
            # Consume before any possible write; an ambiguous failure is never
            # automatically retried, even if the same button request is repeated.
            self._plan=None
            self._view.update(can_create=False,revision=None)
            if self._view['preview'] is not None:self._view['preview']['checked']=False
            try:
                self._destination=create_storage(self._api,plan)
                if self._state_directory is not None:save_naming(self._state_directory,plan.naming)
            except StorageDiscoveryError as error:
                self._view.update(phase='MANUAL_REQUIRED',storage=None,error=manual_path_prompt(error,self._language))
            except RenameRequired as error:
                self._view.update(phase='RENAME_REQUIRED',error=describe_setup_error(error,self._language))
            except Exception as error:
                # Unexpected exceptions may follow an already committed mkdir.
                # Keep the folder for review; never adopt/remove/chmod/retry it.
                safe=describe_setup_error(error if isinstance(error,(SetupIncomplete,DestinationChanged)) else SetupIncomplete(),self._language)
                self._view.update(phase='REVIEW_REQUIRED',error=safe)
            else:
                self._view.update(phase='COMPLETE',error=None)
                if self._view['preview'] is not None:
                    self._view['preview'].update(created=True,checked=True,notice=('Folder został utworzony. Nazwa archiwum jest przykładem; kopia nie została jeszcze wykonana.' if self._language=='pl' else 'Folder created. The archive name is an example; no backup has been performed.'))
            return self.view()



def installation_fields(language='en'):
    pl=language=='pl'
    return [
        {'name':'parent','label':'Miejsce przechowywania kopii zapasowych Plex' if pl else 'Plex backup storage location',
         'description':('Wpisz ścieżkę, w której aplikacja ma utworzyć folder na kopie i logi. Możesz wskazać bezpośrednio dataset, np. /mnt/Archiwum, albo istniejący w nim folder, np. /mnt/Archiwum/Kopie.' if pl else
                        'Enter the path where the application should create the folder for backups and logs. You can use a dataset directly, e.g. /mnt/Archive, or an existing folder within it, e.g. /mnt/Archive/Backups.'),
         'value':'','required':True,'editable':True,'kind':'absolute_host_path'},
        {'name':'folder_name','label':'Nazwa nowego folderu na kopie i logi' if pl else 'New folder name for backups and logs',
         'description':('Ten folder zostanie utworzony we wskazanej lokalizacji. Domyślnie: Plex Backup.' if pl else
                        'This folder will be created in the selected location. Default: Plex Backup.'),
         'value':'Plex Backup','required':False,'editable':True},
        {'name':'archive_prefix','label':'Początek nazwy plików kopii zapasowych' if pl else 'Backup filename prefix',
         'description':('Domyślnie: PlexConfig. Data i godzina zostaną dopisane automatycznie.' if pl else
                        'Default: PlexConfig. The date and time will be added automatically.'),
         'value':'PlexConfig','required':False,'editable':True},
        {'name':'logs_folder','label':'Folder logów' if pl else 'Log folder',
         'value':'Logs','editable':False},
        {'name':'archive_suffix','label':'Data, godzina i rozszerzenie' if pl else 'Date, time and extension',
         'value':'_YYYY.MM.DD_GG.MM.SS.tar.gz' if pl else '_YYYY.MM.DD_HH.MM.SS.tar.gz','editable':False},
    ]



def installation_preview(parent, *, folder_name=None, archive_prefix=None, language='en', instant=None):
    """Pure input preview: no host calls, path probes, reservations or creation."""
    if (not isinstance(parent,str) or not parent.startswith('/') or parent.startswith('//')
            or any(ord(c)<32 for c in parent) or '\\' in parent):
        raise ValueError('Enter an absolute TrueNAS path')
    path=PurePosixPath(parent)
    if path==PurePosixPath('/') or '..' in path.parts:raise ValueError('Enter an absolute TrueNAS path')
    naming=Naming.from_input(folder_name,archive_prefix)
    root=path/naming.folder_name
    name=archive_name(instant if instant is not None else datetime.now(timezone.utc),prefix=naming.archive_prefix)
    pl=language=='pl'
    return {'folder':str(root),'logs':str(root/'Logs'),'archive':name,'archive_path':str(root/name),
            'example':True,'checked':False,'created':False,
            'folder_label':'Folder zostanie utworzony tutaj:' if pl else 'The folder will be created here:',
            'logs_label':'Logi:' if pl else 'Logs:',
            'archive_label':'Przykładowa kopia:' if pl else 'Example backup:',
            'notice':'To podgląd. Folder i plik nie zostały jeszcze utworzone.' if pl else 'Preview only. The folder and file have not been created.'}
