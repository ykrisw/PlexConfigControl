"""Trusted installer controller, not a WWW endpoint or host-execution grant."""
import secrets
from pathlib import Path
from threading import RLock

from .installation_storage import plan_storage, create_storage, manual_path_prompt
from .plex_storage import StorageDiscoveryError
from .storage import describe_setup_error, RenameRequired, SetupIncomplete, DestinationChanged


class InstallationStorageFlow:
    """Explicit check -> exact plan confirmation -> single creation attempt.

    The deployment owns this controller and its API client. No browser can supply
    an API method/dataset or promote a discovery result into execution authority.
    """
    def __init__(self, api, language='en'):
        self._api=api
        self._language='pl' if language=='pl' else 'en'
        self._lock=RLock()
        self._plan=None
        self._destination=None
        self._view={'phase':'UNVERIFIED','revision':None,'can_create':False,
                    'manual_entry_available':True,'error':None,'storage':None}

    def view(self):
        import copy
        with self._lock:return copy.deepcopy(self._view)

    def check(self, parent, *, manual_source=None):
        with self._lock:
            if self._view['phase'] in ('COMPLETE','REVIEW_REQUIRED'):
                return self.view()
            # Any fresh check invalidates the previous revision, even on failure.
            self._plan=None
            self._view.update(phase='UNVERIFIED',revision=None,can_create=False,error=None,storage=None)
            try:
                plan=plan_storage(self._api,parent,manual_source=manual_source)
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
            self._view.update(phase='READY',revision=secrets.token_hex(16),can_create=True,
                storage={'type':plan.plex.storage_type,'source':plan.plex.source,'dataset':plan.plex.dataset,
                         'output':str(Path(plan.parent)/'Plex Config')})
            return self.view()

    def create(self, revision, *, confirmed=False):
        with self._lock:
            if self._view['phase'] in ('COMPLETE','REVIEW_REQUIRED'):
                return self.view()
            if (confirmed is not True or self._view['phase']!='READY' or self._plan is None
                    or not isinstance(revision,str) or revision!=self._view['revision']):
                return self.view()  # No write for stale/unconfirmed plans.
            plan=self._plan
            # Consume before any possible write; an ambiguous failure is never
            # automatically retried, even if the same button request is repeated.
            self._plan=None
            self._view.update(can_create=False,revision=None)
            try:
                self._destination=create_storage(self._api,plan)
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
            return self.view()
