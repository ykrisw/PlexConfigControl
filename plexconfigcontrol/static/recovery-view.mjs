import {createRecoveryController} from './recovery-controller.mjs';

export function mountRecoveryView(root,client,{language='en'}={}){
  const pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  root.classList.add('pcc-notice');root.hidden=true;
  root.setAttribute('role','status');root.setAttribute('aria-live','polite');
  root.innerHTML='<strong data-recovery-title></strong><p data-recovery-snapshot></p><p data-recovery-status></p><p data-recovery-warning></p><p data-recovery-limit></p><button type="button" data-recovery-refresh></button>';
  const find=selector=>root.querySelector(selector);
  const controller=createRecoveryController(client,state=>{
    root.hidden=!state.visible;
    if(!state.visible)return;
    find('[data-recovery-title]').textContent=tx('Recovery required','Wymagane odzyskiwanie');
    find('[data-recovery-snapshot]').textContent=state.data?.snapshot_id?
      `${tx('Recorded snapshot','Zapisany snapshot')}: ${state.data.snapshot_id}`:
      tx('Snapshot identity is not confirmed. Check the operation details.','Nie potwierdzono identyfikatora snapshotu. Sprawdź szczegóły operacji.');
    const labels={PRESENT:tx('Snapshot presence confirmed.','Potwierdzono obecność snapshotu.'),
      ABSENT:tx('Snapshot absence confirmed. Operation cleanup still requires verification.','Potwierdzono brak snapshotu. Nadal trzeba zweryfikować sprzątanie po operacji.'),
      NONE:tx('No snapshot is recorded. Archive publication or temporary files may still require verification.','Nie zapisano snapshotu. Publikacja archiwum lub pliki tymczasowe mogą nadal wymagać weryfikacji.'),
      UNKNOWN:tx('Snapshot state could not be confirmed. New operations remain blocked.','Nie udało się potwierdzić stanu snapshotu. Nowe operacje pozostają zablokowane.')};
    find('[data-recovery-status]').textContent=state.loading?tx('Checking recovery status…','Sprawdzanie stanu odzyskiwania…'):
      labels[state.error?'UNKNOWN':state.data?.snapshot_state]||labels.UNKNOWN;
    const warning=find('[data-recovery-warning]');warning.hidden=!state.data?.loses_restore_recovery_point;
    warning.textContent=tx('Deleting a retained Restore snapshot removes that rollback recovery point.','Usunięcie zachowanego snapshotu Restore oznacza utratę tego punktu odzyskiwania.');
    find('[data-recovery-limit]').textContent=tx('Snapshot removal is unavailable in this installation. This view does not change Plex, archives or snapshots.','Usuwanie snapshotów jest niedostępne w tej instalacji. Ten widok nie zmienia stanu Plex, archiwów ani snapshotów.');
    find('[data-recovery-refresh]').textContent=tx('Refresh status','Odśwież stan');
    find('[data-recovery-refresh]').disabled=state.loading;
  });
  const events=new AbortController();
  find('[data-recovery-refresh]').addEventListener('click',()=>void controller.refresh(),{signal:events.signal});
  return{observe:value=>controller.observe(value),dispose(){events.abort();controller.dispose();root.replaceChildren();root.hidden=true;}};
}
