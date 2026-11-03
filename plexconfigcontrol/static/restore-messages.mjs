import {normalizeOutcome} from './operation-outcome.mjs';
const polish={
  'Regular archive file required':'Archiwum musi być zwykłym plikiem.',
  'Archive must be a regular file':'Archiwum musi być zwykłym plikiem.',
  'Too many entries':'Archiwum zawiera zbyt wiele wpisów.',
  'Unsafe or duplicate path':'Archiwum zawiera niedozwoloną lub powtórzoną ścieżkę.',
  'Links and special files unsupported':'Archiwum zawiera nieobsługiwane dowiązania lub pliki specjalne.',
  'Size limit exceeded':'Przekroczono dozwolony rozmiar zawartości archiwum.',
  'Incomplete file':'Plik wewnątrz archiwum jest niekompletny.',
  'Required Plex files missing':'Brak wymaganych plików konfiguracji Plex.',
  'Stream limit exceeded':'Przekroczono limit rozpakowanego strumienia gzip.',
  'Corrupt or unreadable archive':'Archiwum jest uszkodzone lub nie można go odczytać.',
  'Archive changed during validation':'Archiwum zmieniło się podczas weryfikacji.',
  'Archive is unavailable or unreadable':'Archiwum jest niedostępne lub nie można go odczytać.',
  'Archive location is not configured':'Lokalizacja archiwów nie została skonfigurowana.',
  'Archive location is unavailable':'Lokalizacja archiwów jest niedostępna.',
  'Another operation or recovery must finish':'Najpierw zakończ poprzednią operację lub odzyskiwanie.',
  'Another operation is running':'Trwa inna operacja.',
  'Choose a recognized backup archive':'Wybierz archiwum o obsługiwanej nazwie kopii zapasowej.',
  'Application restarted before validation completed':'Aplikacja uruchomiła się ponownie przed zakończeniem weryfikacji.',
  'Validation could not be started':'Nie udało się rozpocząć weryfikacji.',
  'Sign in required':'Zaloguj się ponownie.',
  'Restore confirmation changed. Refresh and confirm again.':'Potwierdzenie przywracania jest nieaktualne. Odśwież i potwierdź ponownie.',
};

export function restoreError(message,language='en'){
  if(!message)return '';
  return language==='pl'?(polish[message]||`Nie udało się wykonać żądania. Szczegóły: ${message}`):String(message);
}

export function restorePresentation(state,language='en'){
  const pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  const operation=state.snapshot?.operation?.operation,phase=operation?.phase;
  const restore=operation?.kind==='RESTORE';
  const unresolved=state.snapshot?.operation?.publication?.pending===true;
  const executing=restore&&normalizeOutcome(operation.outcome)?.code==='RESTORE_IN_PROGRESS';
  const admitted=state.submission?.blocked===true||['QUEUED','RUNNING','RECOVERY_REQUIRED'].includes(state.snapshot?.operation?.execution?.state);
  const waiting=!admitted&&!executing&&!unresolved&&restore&&['WAITING_FOR_PLEX_STOP','READY'].includes(phase);
  const active=admitted||executing||unresolved||['VALIDATING','RUNNING','RECOVERY_REQUIRED'].includes(phase);
  const details=restore?operation.validation_details:null;
  let notice=restoreError(state.error,language);
  if(!notice&&['FAILED','INTERRUPTED'].includes(details?.status))notice=restoreError(details.reason,language);
  if(!notice&&executing)notice=tx('Restore is in progress. Plex will not be started by this panel.','Restore jest w toku. Panel nie uruchomi Plex.');
  if(!notice&&(unresolved||phase==='RECOVERY_REQUIRED'))notice=tx('Recovery or cleanup must be completed before continuing.','Przed kontynuowaniem trzeba zakończyć odzyskiwanie lub sprzątanie.');
  const readiness=state.snapshot?.readiness;
  if(!notice&&waiting){
    const reasons={
      STOP_PLEX_MANUALLY:tx('Archive validated. Stop Plex manually in TrueNAS Apps. This panel will wait.','Archiwum zweryfikowane. Zatrzymaj Plex ręcznie w TrueNAS Apps. Panel będzie czekał.'),
      PLEX_STOP_NOT_CONFIRMED:tx('Plex is not confirmed stopped. Restore remains blocked.','Nie potwierdzono zatrzymania Plex. Przywracanie pozostaje zablokowane.'),
      ARCHIVE_CHANGED_REVALIDATE:tx('The archive changed. Cancel preparation, then validate it again.','Archiwum zmieniło się. Anuluj przygotowanie, a następnie zweryfikuj je ponownie.'),
      RECOVERY_REQUIRED:tx('Recovery or cleanup is required.','Wymagane jest odzyskiwanie lub sprzątanie.'),
      VALIDATE_ARCHIVE_FIRST:tx('Validate the selected archive before continuing.','Przed kontynuowaniem zweryfikuj wybrane archiwum.'),
    };
    notice=readiness?.ready===true&&readiness.plex?.state==='STOPPED'&&readiness.plex?.available!==false?
      state.snapshot?.capabilities?.restore_execute===true?
        tx('Archive validated and Plex is stopped. Confirm the selected archive to restore.','Archiwum zweryfikowane i Plex zatrzymany. Potwierdź wybrane archiwum, aby je przywrócić.'):
        tx('Archive validated and Plex is stopped. Restore execution is disabled in this installation.','Archiwum zweryfikowane i Plex zatrzymany. Wykonywanie przywracania jest wyłączone w tej instalacji.'):
      reasons[readiness?.reason]||tx('Checking Restore readiness…','Sprawdzanie gotowości przywracania…');
  }
  const progress=state.snapshot?.operation?.progress;
  let progressText='';
  if(restore&&phase==='VALIDATING'&&progress){
    const stages={READING_ARCHIVE:tx('Reading archive files','Odczyt plików archiwum'),CHECKING_GZIP:tx('Checking gzip stream','Sprawdzanie strumienia gzip'),HASHING_ARCHIVE:tx('Calculating archive checksum','Obliczanie sumy kontrolnej archiwum')};
    const done=Number.isFinite(progress.done)&&progress.done>=0?progress.done:0;
    const elapsed=Number.isFinite(progress.elapsed_seconds)&&progress.elapsed_seconds>=0?Math.floor(progress.elapsed_seconds):0;
    progressText=`${stages[progress.stage]||tx('Archive validation','Weryfikacja archiwum')} · ${done.toLocaleString(pl?'pl-PL':'en-GB')} ${tx('bytes read','odczytanych bajtów')} · ${elapsed} s`;
  }
  if(executing&&progress?.operation==='RESTORE'&&progress.active===true){
    const stages={PREPARING:tx('Preparing Restore','Przygotowanie Restore'),
      CREATING_SNAPSHOT:tx('Creating emergency snapshot','Tworzenie awaryjnego snapshotu'),
      RESTORING:tx('Restoring configuration','Przywracanie konfiguracji'),
      VERIFYING_RESTORE:tx('Verifying restored configuration','Weryfikacja przywróconej konfiguracji'),
      ROLLING_BACK:tx('Recovering previous configuration','Odzyskiwanie poprzedniej konfiguracji'),
      REMOVING_SNAPSHOT:tx('Removing emergency snapshot','Usuwanie awaryjnego snapshotu')};
    const elapsed=Number.isFinite(progress.elapsed_seconds)&&progress.elapsed_seconds>=0?Math.floor(progress.elapsed_seconds):0;
    progressText=`${stages[progress.stage]||tx('Restore in progress','Restore w toku')} · ${elapsed} s`;
  }
  return {notice,progressText,waiting,active,
    validateDisabled:!state.selected||state.busy||!operation||waiting||active,
    cancelVisible:waiting,cancelDisabled:state.busy,selectionDisabled:state.busy||waiting||active||!operation};
}
