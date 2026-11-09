import {mountOperationWorkspace,activeExecution} from './operation-workspace.mjs';
import {submissionText} from './submission-controller.mjs';
import {backupResult} from './operation-outcome.mjs';
import {mountRecoveryView} from './recovery-view.mjs';
import {createBackupController,archiveIdentity} from './backup-controller.mjs';

export function mountBackupView(root,client,{language='en',timezone='Europe/London'}={}){
  const document=root.ownerDocument,pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  root.classList.add('pcc-backup');
  root.innerHTML=`
    <section class="pcc-plex"><strong data-server></strong><span data-plex-state="UNKNOWN">UNKNOWN</span></section>
    <section class="pcc-card pcc-backup-action pcc-action-card"><div class="pcc-heading"><h2 data-create-heading></h2><button type="button" data-refresh></button></div>
      <p data-description></p><label class="pcc-backup-name"><span data-prefix-label></span>
        <input data-backup-prefix type="text" maxlength="64" pattern="[A-Za-z0-9][A-Za-z0-9_\\-]{0,63}" aria-describedby="pcc-backup-prefix-help" autocomplete="off" spellcheck="false"></label>
      <p id="pcc-backup-prefix-help" data-prefix-help></p><button type="button" class="pcc-primary" data-create disabled></button>
      <p data-execution-note></p><p data-plan></p>
    </section>
    <section class="pcc-card pcc-operation-workspace" hidden>
      <h2 data-operation-heading></h2>
      <p data-backup-progress role="status" aria-live="polite" hidden></p>
      <div class="pcc-backup-progress" hidden>
        <progress max="100" aria-label="${tx('Current backup stage progress','Postęp bieżącego etapu kopii')}"></progress>
        <span data-backup-percent aria-hidden="true" hidden></span>
      </div>
      <section data-recovery hidden></section>
      <div data-submission class="pcc-notice" role="status" aria-live="polite" hidden><p data-submission-text></p>
        <button type="button" data-submission-check hidden></button><button type="button" data-submission-retry hidden></button></div><p data-operation-result class="pcc-notice" role="status" aria-live="polite" hidden></p>
      <button type="button" data-return-to-archives hidden></button>
    </section>
    <section class="pcc-card pcc-archives"><div class="pcc-heading"><h2 data-existing></h2><button type="button" data-delete disabled></button></div>
      <p data-access-note hidden></p><p class="pcc-notice" data-notice role="status" aria-live="polite" hidden></p><p data-empty role="status"></p><div class="pcc-scroll-list" data-archives></div></section>
    <section class="pcc-card pcc-important"><div class="pcc-heading"><h2 data-important></h2><span data-count></span></div><p data-important-text></p></section>
    <dialog class="pcc-notification-dialog pcc-password-dialog" aria-label="Confirm archive deletion"><h3 data-confirm-heading></h3><p data-confirm-text></p>
      <ul data-confirm-files></ul><div class="pcc-dialog-actions"><button type="button" data-cancel></button><button type="button" data-confirm></button></div></dialog>
    <dialog data-backup-dialog class="pcc-notification-dialog pcc-password-dialog"><h3 data-backup-heading></h3><p data-backup-question></p><p><strong data-backup-archive></strong></p><p data-confirm-prefix hidden></p>
      <div class="pcc-dialog-actions"><button type="button" data-backup-cancel></button><button type="button" data-backup-another></button><button type="button" data-backup-overwrite></button></div></dialog>`;
  const find=selector=>root.querySelector(selector),list=find('[data-archives]'),dialog=find('dialog'),backupDialog=find('[data-backup-dialog]');
  const labels={
    '[data-server]':tx('Plex Server','Serwer Plex'),'[data-create-heading]':tx('Create a new backup','Utwórz nową kopię zapasową'),
    '[data-refresh]':tx('Refresh','Odśwież'),'[data-description]':tx('Create and verify a new copy of your Plex configuration.','Utwórz i zweryfikuj nową kopię konfiguracji Plex.'),
    '[data-operation-heading]':tx('Backup status','Stan kopii zapasowej'),
    '[data-return-to-archives]':tx('Return to archives','Wróć do listy kopii'),
    '[data-prefix-label]':tx('Archive name prefix','Początek nazwy archiwum'),
    '[data-prefix-help]':tx('Optional. Use 1–64 letters A–Z, digits, underscores or hyphens. Start with a letter or digit. The date and .tar.gz are added automatically.','Opcjonalnie. Użyj 1–64 liter A–Z, cyfr, podkreśleń lub myślników. Zacznij od litery lub cyfry. Data i rozszerzenie .tar.gz zostaną dodane automatycznie.'),
    '[data-create]':tx('Create Backup','Utwórz kopię zapasową'),'[data-existing]':tx('Existing Backups','Istniejące kopie zapasowe'),
    '[data-delete]':tx('Delete Selected Archives','Usuń zaznaczone archiwa'),'[data-important]':tx('Important','Ważne'),
    '[data-important-text]':tx('Existing backups will not be deleted automatically. Each completed backup is verified before it becomes available.','Istniejące kopie nie są usuwane automatycznie. Każda nowa kopia jest weryfikowana, zanim stanie się dostępna.'),
    '[data-execution-note]':tx('Backup creation is not connected in this development build. Plex will not be stopped.','Tworzenie kopii nie jest jeszcze podłączone w tej wersji. Plex nie zostanie zatrzymany.'),
    '[data-confirm-heading]':tx('Delete Selected Archives','Usuń zaznaczone archiwa'),
    '[data-confirm-text]':tx('Permanently delete these archive files? Permanent logs and other archives will remain untouched.','Trwale usunąć te pliki archiwów? Trwałe logi i pozostałe archiwa pozostaną nietknięte.'),
    '[data-cancel]':tx('Cancel','Anuluj'),'[data-confirm]':tx('Delete','Usuń'),
    '[data-backup-heading]':tx('One backup already exists','Istnieje już jedna kopia'),
    '[data-backup-question]':tx('Create another dated copy or replace this archive? The existing archive is retained until the new copy is verified and its temporary snapshot removed.','Utworzyć kolejną kopię z datą czy zastąpić to archiwum? Dotychczasowe archiwum pozostanie do czasu weryfikacji nowej kopii i usunięcia jej tymczasowego snapshotu.'),
    '[data-backup-cancel]':tx('Cancel','Anuluj'),'[data-backup-another]':tx('Create Another Copy','Utwórz kolejną kopię'),
    '[data-backup-overwrite]':tx('Overwrite Existing','Nadpisz istniejącą'),
    '[data-submission-check]':tx('Check Status','Sprawdź stan'),'[data-submission-retry]':tx('Retry Same Request','Ponów to samo żądanie'),
  };
  for(const [selector,text]of Object.entries(labels))find(selector).textContent=text;
  dialog.setAttribute('aria-label',tx('Confirm archive deletion','Potwierdź usunięcie archiwów'));
  backupDialog.setAttribute('aria-label',tx('Choose Backup Action','Wybierz działanie kopii zapasowej'));
  const dateFormat=new Intl.DateTimeFormat(pl?'pl-PL':'en-GB',{dateStyle:'medium',timeZone:timezone});
  const percentFormat=new Intl.NumberFormat(pl?'pl-PL':'en-GB',{style:'percent',maximumFractionDigits:1});
  const recovery=mountRecoveryView(find('[data-recovery]'),client,{language});
  const lifecycle=new AbortController();let state,confirmation=[],backupConfirmation=null,disposed=false;
  const prefix=find('[data-backup-prefix]');
  const showWorkspace=mountOperationWorkspace(root,find('.pcc-archives'),lifecycle.signal);
  const stages={
    PREPARING:tx('Preparing backup…','Przygotowywanie kopii…'),
    CREATING_SNAPSHOT:tx('Creating a temporary snapshot…','Tworzenie tymczasowej migawki…'),
    CREATING_ARCHIVE:tx('Creating the archive…','Tworzenie archiwum…'),
    VERIFYING_ARCHIVE:tx('Verifying the archive…','Weryfikowanie archiwum…'),
    REMOVING_SNAPSHOT:tx('Removing the temporary snapshot…','Usuwanie tymczasowej migawki…'),
    PUBLISHING_ARCHIVE:tx('Saving the verified archive…','Zapisywanie zweryfikowanego archiwum…'),
  };
  function render(value){
    state=value;recovery.observe(value.operation);
    const result=find('[data-operation-result]');result.textContent=value.submission.blocked?'':backupResult(value.operation,language);result.hidden=!result.textContent;
    const status=find('[data-plex-state]');status.dataset.plexState=value.plex;
    status.textContent=pl?({RUNNING:'DZIAŁA',STOPPED:'ZATRZYMANY',UNKNOWN:'NIEZNANY'})[value.plex]:value.plex;
    find('[data-refresh]').disabled=value.loading||value.busy||dialog.open||backupDialog.open;
    find('[data-create]').disabled=!value.canCreate||dialog.open||backupDialog.open;
    find('[data-execution-note]').textContent=value.creationEnabled?tx('Plex will keep running. The archive is read only from a temporary snapshot.','Plex będzie działał. Archiwum jest odczytywane wyłącznie z tymczasowego snapshotu.'):
      tx('Backup creation is disabled in this installation. Plex will not be stopped.','Tworzenie kopii jest wyłączone w tej instalacji. Plex nie zostanie zatrzymany.');
    const draftMatches=backupConfirmation&&value.entries.length===1&&archiveIdentity(backupConfirmation)===archiveIdentity(value.entries[0]);
    find('[data-backup-another]').disabled=!value.canCreate||!draftMatches;
    find('[data-backup-overwrite]').disabled=!value.canCreate||!draftMatches||!value.overwriteEnabled;
    find('[data-backup-cancel]').disabled=value.submission.busy;
    find('[data-submission-text]').textContent=submissionText(value.submission,language);
    find('[data-submission]').hidden=!find('[data-submission-text]').textContent||Boolean(result.textContent);
    const snapshot=value.operation;
    const active=value.submission.blocked||activeExecution(snapshot,'BACKUP')||
      (snapshot?.operation?.kind==='BACKUP'&&snapshot.operation.phase==='RUNNING');
    const recoveryVisible=!find('[data-recovery]').hidden;
    const locked=showWorkspace({
      active:active||recoveryVisible,snapshot,
      result:result.textContent||find('[data-submission-text]').textContent,
    });
    const progress=find('[data-backup-progress]');
    const stage=snapshot?.progress;
    progress.textContent=locked&&!recoveryVisible
      ? !snapshot&&!value.submission.blocked
        ? tx('Waiting to confirm the operation status…','Oczekiwanie na potwierdzenie stanu operacji…')
        : stage?.operation==='BACKUP'&&stage.active===true
          ? stages[stage.stage]||tx('Backup in progress…','Trwa tworzenie kopii zapasowej…')
          : find('[data-submission]').hidden?tx('Waiting for backup status…','Oczekiwanie na stan kopii…'):''
      : '';
    progress.hidden=!progress.textContent;
    const meter=find('.pcc-backup-progress'),bar=meter.querySelector('progress');
    const percent=find('[data-backup-percent]');
    const measured=stage?.operation==='BACKUP'&&stage.active===true&&Number.isFinite(stage.stage_percent);
    meter.hidden=!locked||recoveryVisible;
    if(measured)bar.value=stage.stage_percent;
    else bar.removeAttribute('value');
    percent.hidden=!measured;
    percent.textContent=measured?percentFormat.format(stage.stage_percent/100):'';
    prefix.disabled=locked||backupDialog.open;
    find('[data-plan]').hidden=locked;
    find('[data-submission-check]').hidden=!value.submission.canCheck;
    find('[data-submission-retry]').hidden=!value.submission.canRetry;
    find('[data-delete]').disabled=!value.canDelete||!value.selected.length||value.selected.length>1000||value.loading||value.busy;
    find('[data-cancel]').disabled=value.busy;
    find('[data-confirm]').disabled=!value.canDelete||value.loading||value.busy;
    find('[data-access-note]').hidden=!value.available||value.canDelete;
    find('[data-access-note]').textContent=value.deletionEnabled?
      tx('Finish the current operation or recovery before deleting archives.','Przed usuwaniem archiwów zakończ bieżącą operację lub odzyskiwanie.'):
      tx('Archive deletion is disabled in this installation.','Usuwanie archiwów jest wyłączone w tej instalacji.');
    find('[data-count]').textContent=value.available?`${value.entries.length} ${tx('backups','kopii')}`:`— ${tx('backups','kopii')}`;
    const messages={DELETED:tx('Selected archives deleted. Permanent log files were preserved.','Usunięto zaznaczone archiwa. Trwałe pliki logów zostały zachowane.'),
      DELETE_UNCONFIRMED:tx('Deletion could not be fully confirmed. Review the refreshed list before trying again.','Nie udało się w pełni potwierdzić usunięcia. Przed kolejną próbą sprawdź odświeżoną listę.')};
    find('[data-notice]').textContent=value.error||messages[value.notice]||'';find('[data-notice]').hidden=!find('[data-notice]').textContent;
    find('[data-empty]').hidden=value.entries.length>0;
    find('[data-empty]').textContent=value.loading?tx('Loading archives…','Wczytywanie archiwów…'):value.available?tx('No backup archives found.','Nie znaleziono archiwów.'):tx('Archive location is not available.','Lokalizacja archiwów jest niedostępna.');
    const plans={CREATE_NEW:tx('The next backup will create a new dated copy.','Następna kopia otrzyma nową nazwę z datą.'),
      ASK_OVERWRITE_OR_NEW:tx('One archive exists: before the next backup, choose whether to overwrite it or create another dated copy.','Istnieje jedno archiwum: przed następną kopią wybierzesz nadpisanie albo utworzenie kolejnej kopii z datą.')};
    find('[data-plan]').textContent=value.plan?plans[value.plan.action]||'':value.available?tx('Backup planning is unavailable while another operation or recovery is pending.','Planowanie kopii jest niedostępne podczas innej operacji lub oczekiwania na odzyskanie.'):'';
    const scroll=list.scrollTop;const focus=list.contains(document.activeElement)?document.activeElement.dataset.archiveName:null;
    list.replaceChildren();
    for(const archive of value.entries){
      const row=document.createElement('label');row.className='pcc-archive-row';
      const input=document.createElement('input');input.type='checkbox';input.dataset.archiveName=archive.name;
      input.checked=value.selected.includes(archive.name);input.disabled=value.loading||value.busy||!value.available||dialog.open;
      input.setAttribute('aria-label',`${tx('Select','Zaznacz')}: ${archive.name}`);row.classList.toggle('pcc-selected',input.checked);
      const text=document.createElement('span'),name=document.createElement('strong'),metadata=document.createElement('small');name.textContent=archive.name;
      const milliseconds=Number(BigInt(archive.modified_ns)/1000000n);
      const date=Number.isFinite(new Date(milliseconds).getTime())?dateFormat.format(new Date(milliseconds)):'';
      metadata.textContent=`${date} · ${(Number(archive.size)/1024**3).toFixed(2)} GiB`;text.append(name,metadata);row.append(input,text);list.append(row);
      if(archive.name===focus)input.focus({preventScroll:true});
    }
    list.scrollTop=scroll;
  }
  const controller=createBackupController(client,render),options={signal:lifecycle.signal};
  root.addEventListener('change',event=>{const input=event.target.closest('[data-archive-name]');if(input)controller.select(input.dataset.archiveName,input.checked);},options);
  find('[data-refresh]').addEventListener('click',()=>void controller.refresh(),options);
  find('[data-create]').addEventListener('click',()=>{
    if(!prefix.reportValidity())return;
    const choice=controller.prepareBackup();if(!choice)return;
    if(choice.mode==='NEW'){void controller.startBackup('NEW',null,prefix.value);return;}
    backupConfirmation=choice.archive;find('[data-backup-archive]').textContent=choice.archive.name;
    const confirmedPrefix=find('[data-confirm-prefix]');
    confirmedPrefix.hidden=!prefix.value;
    confirmedPrefix.textContent=tx('New archive name prefix: ','Początek nazwy nowego archiwum: ')+prefix.value;
    backupDialog.showModal();render(state);
  },options);
  find('[data-backup-cancel]').addEventListener('click',()=>backupDialog.close(),options);
  backupDialog.addEventListener('cancel',event=>{if(state.submission.busy)event.preventDefault();},options);
  backupDialog.addEventListener('close',()=>{backupConfirmation=null;if(!disposed)render(state);},options);
  for(const [selector,mode] of [['[data-backup-another]','ANOTHER'],['[data-backup-overwrite]','OVERWRITE']]){
    find(selector).addEventListener('click',async()=>{if(!backupConfirmation)return;await controller.startBackup(mode,backupConfirmation,prefix.value);if(!disposed)backupDialog.close();},options);
  }
  find('[data-submission-check]').addEventListener('click',()=>void controller.checkSubmission(),options);
  find('[data-submission-retry]').addEventListener('click',()=>void controller.retrySubmission(),options);
  find('[data-delete]').addEventListener('click',()=>{
    confirmation=controller.selection();find('[data-confirm-files]').replaceChildren();
    for(const archive of confirmation){const item=document.createElement('li');item.textContent=archive.name;find('[data-confirm-files]').append(item);}
    dialog.showModal();render(state);
  },options);
  dialog.addEventListener('cancel',event=>{if(state.busy)event.preventDefault();},options);
  dialog.addEventListener('close',()=>{confirmation=[];if(!disposed)render(state);},options);
  find('[data-cancel]').addEventListener('click',()=>dialog.close(),options);
  find('[data-confirm]').addEventListener('click',async()=>{await controller.remove(confirmation);if(!disposed)dialog.close();},options);
  return()=>{disposed=true;lifecycle.abort();controller.dispose();recovery.dispose();if(dialog.open)dialog.close();if(backupDialog.open)backupDialog.close();root.replaceChildren();root.classList.remove('pcc-backup');};
}
