import {mountOperationWorkspace,activeExecution} from './operation-workspace.mjs';
import {submissionText} from './submission-controller.mjs';
import {restoreResult} from './operation-outcome.mjs';
import {mountRecoveryView} from './recovery-view.mjs';
import {bindRestoreControls} from './restore-panel.mjs';
import {restorePresentation,restoreError} from './restore-messages.mjs';

// Mount inside the application's main content area, below the five-tab header.
// Archive names, validation results and errors are always inserted as text.
export function mountRestoreView(root, client, {language='en'}={}) {
  const pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  root.classList.add('pcc-restore');
  root.innerHTML = `
    <link rel="stylesheet" href="/assets/restore-view.css">
    <section class="pcc-plex" aria-label="${tx('Plex status','Stan Plex')}"><strong>${tx('Plex Server','Serwer Plex')}</strong>
      <span data-plex-state="UNKNOWN">${tx('UNKNOWN','NIEZNANY')}</span></section>
    <section class="pcc-card pcc-action-card">
      <div class="pcc-heading"><h2>${tx('Archive Validation','Weryfikacja archiwum')}</h2>
        <button type="button" data-restore-action="refresh">${tx('Refresh','Odśwież')}</button></div>
      <p>${tx('Select an archive and start validation.','Wybierz archiwum i rozpocznij weryfikację.')}</p>
      <button type="button" class="pcc-primary" data-restore-action="validate" disabled>${tx('Validate Archive','Zweryfikuj archiwum')}</button>
    </section>
    <section class="pcc-card pcc-operation-workspace" hidden>
      <h2>${tx('Restore status','Stan przywracania')}</h2>
      <section data-recovery hidden></section>
      <div data-operation-result class="pcc-notice" role="status" aria-live="polite" hidden></div>
      <div data-validation-progress hidden role="status" aria-live="polite"></div>
      <div data-validation-notice class="pcc-notice" hidden role="status" aria-live="polite"></div>
      <div data-submission class="pcc-notice" role="status" aria-live="polite" hidden><p data-submission-text></p>
        <button type="button" data-submission-check hidden></button><button type="button" data-submission-retry hidden></button></div>
      <button type="button" class="pcc-primary" data-restore-execute hidden disabled>${tx('Restore Configuration','Przywróć konfigurację')}</button>
      <button type="button" data-restore-action="cancel" hidden>${tx('Cancel Restore Preparation','Anuluj przygotowanie przywracania')}</button>
      <button type="button" data-return-to-archives hidden>${tx('Return to archives','Wróć do listy kopii')}</button>
    </section>
    <section class="pcc-card pcc-archive-card"><div class="pcc-heading"><h2>${tx('Select Backup Archive','Wybierz archiwum kopii zapasowej')}</h2></div>
      <div data-archive-list role="group" aria-label="${tx('Backup archives','Archiwa kopii zapasowych')}"></div>
      <p data-archive-message role="status">${tx('Loading archives…','Wczytywanie archiwów…')}</p>
    </section>
    <dialog data-restore-dialog class="pcc-notification-dialog pcc-password-dialog" aria-label="${tx('Confirm Restore','Potwierdź przywracanie')}"><form data-restore-confirm-form>
      <h3>${tx('Confirm Restore','Potwierdź przywracanie')}</h3><p>${tx('This will replace the current Plex configuration. Plex will remain stopped.','Ta operacja zastąpi bieżącą konfigurację Plex. Plex pozostanie zatrzymany.')}</p>
      <p><strong data-confirm-archive></strong></p><label>${tx('Type RESTORE to confirm','Wpisz RESTORE, aby potwierdzić')}<input data-confirm-restore autocomplete="off" spellcheck="false"></label>
      <div class="pcc-dialog-actions"><button type="button" data-restore-dialog-cancel>${tx('Cancel','Anuluj')}</button><button type="submit" data-restore-dialog-confirm disabled>${tx('Restore','Przywróć')}</button></div>
    </form></dialog>`;
  const find = selector => root.querySelector(selector);
  const list = find('[data-archive-list]');
  const message = find('[data-archive-message]');
  const notice = find('[data-validation-notice]');
  const progress = find('[data-validation-progress]');
  const validate = find('[data-restore-action="validate"]');
  const cancel = find('[data-restore-action="cancel"]');
  const status = find('[data-plex-state]');
  const recovery=mountRecoveryView(find('[data-recovery]'),client,{language});
  const lifecycle = new AbortController();
  const showWorkspace=mountOperationWorkspace(root,find('.pcc-archive-card'),lifecycle.signal);
  const dialog=find('[data-restore-dialog]'),confirmationInput=find('[data-confirm-restore]');
  let confirmed=null,disposeControls;
  find('[data-submission-check]').textContent=tx('Check Status','Sprawdź stan');
  find('[data-submission-retry]').textContent=tx('Retry Same Request','Ponów to samo żądanie');
  let selected = null, loading = false, archiveAvailable=false, statusTimer, currentState;

  const render = state => {
    currentState = state;recovery.observe(state.snapshot?.operation);
    const result=find('[data-operation-result]');result.textContent=state.submission?.blocked?'':restoreResult(state.snapshot?.operation,language);result.hidden=!result.textContent;
    selected = state.selected;
    const view=restorePresentation(state,language);
    validate.disabled = view.validateDisabled||loading||!archiveAvailable;
    cancel.hidden = !view.cancelVisible;
    cancel.disabled = view.cancelDisabled;
    const candidate=disposeControls?.prepareExecution();
    find('[data-restore-execute]').hidden=!(state.snapshot?.capabilities?.restore_execute===true&&state.snapshot?.operation?.operation?.kind==='RESTORE'&&view.waiting);
    find('[data-restore-execute]').disabled=!candidate||loading||!archiveAvailable||dialog.open;
    find('[data-restore-dialog-confirm]').disabled=!candidate||loading||!archiveAvailable||confirmationInput.value!=='RESTORE'||
      !confirmed||confirmed.archive!==candidate.archive||confirmed.sha256!==candidate.sha256;
    find('[data-restore-dialog-cancel]').disabled=state.submission?.busy===true;
    find('[data-submission-text]').textContent=submissionText(state.submission,language);
    find('[data-submission]').hidden=!find('[data-submission-text]').textContent||Boolean(result.textContent)||(state.submission?.phase==='RUNNING'&&Boolean(view.notice));
    find('[data-submission-check]').hidden=!state.submission?.canCheck;
    find('[data-submission-retry]').hidden=!state.submission?.canRetry;
    for (const input of list.querySelectorAll('input')) {
      input.disabled = view.selectionDisabled||loading||!archiveAvailable;
      input.checked = input.value === selected;
      input.closest('label').classList.toggle('pcc-selected', input.checked);
    }
    notice.textContent = view.notice;
    notice.hidden = !view.notice;
    const snapshot=state.snapshot?.operation;
    const operation=snapshot?.operation;
    const active=state.busy||state.submission?.blocked===true||view.waiting||activeExecution(snapshot,'RESTORE')||
      (operation?.kind==='RESTORE'&&view.active)||!find('[data-recovery]').hidden;
    const locked=showWorkspace({active,snapshot,result:result.textContent||view.notice||find('[data-submission-text]').textContent});
    progress.textContent=view.progressText||
      (locked&&!view.notice&&find('[data-recovery]').hidden&&find('[data-submission]').hidden
        ? tx('Waiting for restore status…','Oczekiwanie na stan przywracania…'):'');
    progress.hidden=!progress.textContent;
  };
  disposeControls = bindRestoreControls(root, client, render);
  find('[data-restore-execute]').addEventListener('click',()=>{
    const candidate=disposeControls.prepareExecution();if(!candidate||loading||!archiveAvailable)return;
    confirmed=candidate;find('[data-confirm-archive]').textContent=candidate.archive;
    confirmationInput.value='';dialog.showModal();render(currentState);confirmationInput.focus();
  },{signal:lifecycle.signal});
  confirmationInput.addEventListener('input',()=>{if(currentState)render(currentState);},{signal:lifecycle.signal});
  find('[data-restore-dialog-cancel]').addEventListener('click',()=>dialog.close(),{signal:lifecycle.signal});
  dialog.addEventListener('cancel',event=>{if(currentState?.submission?.busy)event.preventDefault();},{signal:lifecycle.signal});
  dialog.addEventListener('close',()=>{confirmed=null;confirmationInput.value='';if(!lifecycle.signal.aborted&&currentState)render(currentState);},{signal:lifecycle.signal});
  find('[data-restore-confirm-form]').addEventListener('submit',async event=>{
    event.preventDefault();if(!confirmed||loading||!archiveAvailable)return;
    await disposeControls.execute(confirmed,confirmationInput.value);if(!lifecycle.signal.aborted)dialog.close();
  },{signal:lifecycle.signal});
  find('[data-submission-check]').addEventListener('click',()=>void disposeControls.checkSubmission(),{signal:lifecycle.signal});
  find('[data-submission-retry]').addEventListener('click',()=>void disposeControls.retrySubmission(),{signal:lifecycle.signal});

  const loadArchives = async () => {
    if (loading) return;
    loading = true;
    if(currentState)render(currentState);
    try {
      const archives = await client.archives(lifecycle.signal);
      if (lifecycle.signal.aborted) return;
      if(!Array.isArray(archives))throw Error('Invalid archive list');
      archiveAvailable=true;
      list.replaceChildren();
      for (const archive of archives) {
        const row = root.ownerDocument.createElement('label');
        row.className = 'pcc-archive-row';
        const input = root.ownerDocument.createElement('input');
        input.type = 'radio'; input.name = 'restore-archive'; input.value = archive.name;
        input.setAttribute('aria-label',`${tx('Select','Zaznacz')}: ${archive.name}`);
        const content = root.ownerDocument.createElement('span');
        const name = root.ownerDocument.createElement('strong');
        name.textContent = archive.name;
        const size = root.ownerDocument.createElement('small');
        size.textContent = `${(archive.size / 1024 ** 3).toFixed(2)} GiB`;
        content.append(name, size); row.append(input, content); list.append(row);
      }
      message.textContent = archives.length ? '' : tx('No backup archives found.','Nie znaleziono archiwów kopii zapasowych.');
      message.hidden = Boolean(archives.length);
      disposeControls.reconcileSelection(archives.map(archive=>archive.name));
      if (currentState) render(currentState);
    } catch (error) {
      if (!lifecycle.signal.aborted) { archiveAvailable=false;message.hidden = false; message.textContent = restoreError(error.message,language); }
    } finally { loading = false;if(!lifecycle.signal.aborted&&currentState)render(currentState); }
  };
  const updatePlex = async () => {
    let value = 'UNKNOWN';
    try {
      const result = await client.status(lifecycle.signal);
      if (result?.available!==false&&['RUNNING', 'STOPPED'].includes(result?.state)) value = result.state;
    } catch { /* A failed read must remove any old green/red status. */ }
    if (lifecycle.signal.aborted) return;
    status.dataset.plexState = value; status.textContent = pl?({RUNNING:'DZIAŁA',STOPPED:'ZATRZYMANY',UNKNOWN:'NIEZNANY'})[value]:value;
    statusTimer = setTimeout(updatePlex, 2000);
  };
  const refreshArchives = event => {
    if (event.target.closest('[data-restore-action="refresh"]')) void loadArchives();
  };
  root.addEventListener('click', refreshArchives, {signal: lifecycle.signal});
  void loadArchives(); void updatePlex();
  return () => {
    lifecycle.abort(); clearTimeout(statusTimer); disposeControls(); recovery.dispose();
    if(dialog.open)dialog.close();
    root.replaceChildren(); root.classList.remove('pcc-restore');
  };
}
