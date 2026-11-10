import {createIntegrationController} from './integration-controller.mjs';

export function mountIntegrationView(root,client,{language='en'}={}){
  let currentLanguage=language,last={loading:false,data:null,error:false};
  root.classList.add('pcc-integration');
  root.innerHTML='<h3 data-integration-title></h3><p data-integration-description></p><button type="button" data-integration-check></button><dl data-integration-checks></dl><p data-integration-checked></p><p class="pcc-notice" data-integration-error role="status" aria-live="polite" hidden></p>';
  const find=selector=>root.querySelector(selector),document=root.ownerDocument;
  function render(state){
    last=state;const pl=currentLanguage==='pl',tx=(en,polish)=>pl?polish:en;
    find('[data-integration-title]').textContent=tx('Connection checks','Sprawdzanie połączenia');
    find('[data-integration-description]').textContent=tx('Read-only checks. No snapshots, Plex changes or permission changes.','Sprawdzenie tylko do odczytu. Bez tworzenia snapshotów, zmian Plex ani uprawnień.');
    const button=find('[data-integration-check]');button.disabled=state.loading;
    button.textContent=state.loading?tx('Checking…','Sprawdzanie…'):tx('Run checks','Sprawdź połączenie');
    const unchecked=tx('Not checked','Nie sprawdzono');
    const labels={NOT_CHECKED:unchecked,NOT_CONFIGURED:tx('Not configured','Nie skonfigurowano'),
      UNAVAILABLE:tx('Read could not be confirmed','Nie potwierdzono odczytu'),
      NO_RECORDED_SNAPSHOT:tx('Configured; no recorded snapshot to verify access','Skonfigurowano; brak zapisanego snapshotu do sprawdzenia dostępu'),
      PRESENT:tx('Recorded snapshot presence confirmed','Potwierdzono obecność zapisanego snapshotu'),
      ABSENT:tx('Recorded snapshot absence confirmed','Potwierdzono brak zapisanego snapshotu'),
      UNKNOWN:tx('Could not be confirmed','Nie udało się potwierdzić'),
      BUSY:tx('Another operation is busy; retry after it finishes','Trwa inna operacja; sprawdź ponownie po jej zakończeniu'),
      CHANGED:tx('Operation changed during the check; refresh the results','Operacja zmieniła się podczas sprawdzania; odśwież wyniki'),
      RECOVERY_REQUIRED:tx('Recovery or cleanup requires review','Wymagane sprawdzenie odzyskiwania lub sprzątania'),
      ACTIVE:tx('Operation is recorded as active','Zapisana operacja jest w toku'),
      WAITING_FOR_USER:tx('Waiting for the user','Oczekiwanie na użytkownika'),
      IDLE:tx('No active operation is recorded','Nie zapisano aktywnej operacji')};
    const data=state.data;
    const appStates={RUNNING:tx('RUNNING','DZIAŁA'),STOPPED:tx('STOPPED','ZATRZYMANY'),
      STOPPING:tx('STOPPING','ZATRZYMYWANIE'),DEPLOYING:tx('DEPLOYING','WDRAŻANIE'),CRASHED:tx('CRASHED','AWARIA')};
    const plex=data?.plex.state==='READ_VERIFIED'?
      tx('Plex status read verified: ','Potwierdzono odczyt stanu Plex: ')+appStates[data.plex.app_state]:labels[data?.plex.state]||unchecked;
    const archives=data?.archives.state==='LIST_VERIFIED'?
      tx('Archive list read verified; count: ','Potwierdzono odczyt listy archiwów; liczba: ')+data.archives.count+
      tx('. File contents were not checked.','. Nie sprawdzano zawartości plików.'):labels[data?.archives.state]||unchecked;
    const rows=[[tx('TrueNAS / Plex status','TrueNAS / stan Plex'),plex],
      [tx('Archive listing','Lista archiwów'),archives],
      [tx('Scoped snapshot read','Odczyt wskazanego snapshotu'),labels[data?.snapshot.state]||unchecked],
      [tx('Operation state','Stan operacji'),labels[data?.operation.state]||unchecked]];
    const list=find('[data-integration-checks]');list.replaceChildren();
    for(const [label,value]of rows){
      const term=document.createElement('dt'),definition=document.createElement('dd');term.textContent=label;definition.textContent=value;list.append(term,definition);
    }
    const checked=find('[data-integration-checked]');
    checked.textContent='';
    if(data){
      const [date,time]=new Date(data.checked_at).toISOString().split('T');
      checked.textContent=`UTC: ${date} ${tx('Time','Czas')}: ${time.slice(0,8)}`;
    }
    const error=find('[data-integration-error]');error.hidden=!state.error;
    error.textContent=tx('Checks could not be confirmed. Previous confirmations were cleared. Try again.','Nie udało się potwierdzić wyników. Poprzednie potwierdzenia zostały usunięte. Spróbuj ponownie.');
  }
  const controller=createIntegrationController(client,render),events=new AbortController();
  find('[data-integration-check]').addEventListener('click',()=>void controller.check(),{signal:events.signal});
  return{setLanguage(value){currentLanguage=value;render(last);},dispose(){events.abort();controller.dispose();root.replaceChildren();}};
}
