import {recoveryOutcome} from './operation-outcome.mjs';
import {createRecoveryController} from './recovery-controller.mjs';

export function mountRecoveryView(root,client,{language='en'}={}){
  const pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  root.classList.add('pcc-notice');root.hidden=true;
  root.setAttribute('role','status');root.setAttribute('aria-live','polite');
  root.innerHTML='<strong data-recovery-title></strong><p data-recovery-outcome hidden></p><p data-recovery-snapshot></p><p data-recovery-status></p><section data-recovery-publication hidden><strong data-publication-title></strong><p data-publication-archive></p><p data-publication-stage></p><p data-publication-older></p><p data-publication-warning></p></section><p data-recovery-warning></p><p data-recovery-limit></p><button type="button" data-recovery-refresh></button>';
  const find=selector=>root.querySelector(selector);
  const controller=createRecoveryController(client,state=>{
    root.hidden=!state.visible;
    if(!state.visible)return;
    find('[data-recovery-title]').textContent=tx('Recovery required','Wymagane odzyskiwanie');
    const outcome=find('[data-recovery-outcome]');outcome.textContent=recoveryOutcome(state.data,language);outcome.hidden=!outcome.textContent;
    find('[data-recovery-snapshot]').textContent=state.data?.snapshot_id?
      `${tx('Recorded snapshot','Zapisany snapshot')}: ${state.data.snapshot_id}`:
      state.data?.snapshot_state==='NONE'?tx('No snapshot is recorded.','Nie zapisano snapshotu.'):
      tx('Snapshot identity is not confirmed. Check the operation details.','Nie potwierdzono identyfikatora snapshotu. Sprawdź szczegóły operacji.');
    const labels={PRESENT:tx('Snapshot presence confirmed.','Potwierdzono obecność snapshotu.'),
      ABSENT:tx('Snapshot absence confirmed. Operation cleanup still requires verification.','Potwierdzono brak snapshotu. Nadal trzeba zweryfikować sprzątanie po operacji.'),
      NONE:tx('No snapshot is recorded. Archive publication or temporary files may still require verification.','Nie zapisano snapshotu. Publikacja archiwum lub pliki tymczasowe mogą nadal wymagać weryfikacji.'),
      UNKNOWN:tx('Snapshot state could not be confirmed. New operations remain blocked.','Nie udało się potwierdzić stanu snapshotu. Nowe operacje pozostają zablokowane.')};
    find('[data-recovery-status]').textContent=state.loading?tx('Checking recovery status…','Sprawdzanie stanu odzyskiwania…'):
      labels[state.error?'UNKNOWN':state.data?.snapshot_state]||labels.UNKNOWN;
    const record=state.data?.publication;
    const publication=find('[data-recovery-publication]');publication.hidden=!record?.pending;
    find('[data-publication-title]').textContent=tx('Interrupted archive publication','Przerwany zapis archiwum');
    find('[data-publication-archive]').textContent=record?.archive?`${tx('Archive','Archiwum')}: ${record.archive}`:'';
    find('[data-publication-stage]').textContent=record?.temporary_file?
      `${tx('Recorded temporary filename (presence not checked)','Zapisana nazwa pliku tymczasowego (nie sprawdzono obecności)')}: ${record.temporary_file}`:'';
    const older=find('[data-publication-older]');older.hidden=!record?.replaced_archive;
    older.textContent=record?.replaced_archive?`${tx('Older archive in replacement record','Starsze archiwum w zapisie zastępowania')}: ${record.replaced_archive}`:'';
    find('[data-publication-warning]').textContent=record?.status==='RECORD_UNREADABLE'?
      tx('The publication record cannot be read safely. Manual investigation is required.','Nie można bezpiecznie odczytać zapisu operacji. Wymagane jest ręczne sprawdzenie.'):
      tx('This is an operation record, not proof that the archive exists or is valid. Full verification and confirmed recovery are still required. Automatic cleanup is disabled.',
         'To zapis operacji, a nie potwierdzenie obecności ani poprawności archiwum. Nadal wymagana jest pełna weryfikacja i potwierdzenie odzyskiwania. Automatyczne sprzątanie jest wyłączone.');
    const warning=find('[data-recovery-warning]');warning.hidden=!state.data?.loses_restore_recovery_point;
    warning.textContent=tx('Deleting a retained Restore snapshot removes that rollback recovery point.','Usunięcie zachowanego snapshotu Restore oznacza utratę tego punktu odzyskiwania.');
    find('[data-recovery-limit]').textContent=tx('Snapshot removal is unavailable in this installation. Publication recovery is also unavailable here. This view does not change Plex, archives or snapshots.','Usuwanie snapshotów jest niedostępne w tej instalacji. Odzyskiwanie przerwanego zapisu również nie jest tu dostępne. Ten widok nie zmienia stanu Plex, archiwów ani snapshotów.');
    find('[data-recovery-refresh]').textContent=tx('Refresh status','Odśwież stan');
    find('[data-recovery-refresh]').disabled=state.loading;
  });
  const events=new AbortController();
  find('[data-recovery-refresh]').addEventListener('click',()=>void controller.refresh(),{signal:events.signal});
  return{observe:value=>controller.observe(value),dispose(){events.abort();controller.dispose();root.replaceChildren();root.hidden=true;}};
}
