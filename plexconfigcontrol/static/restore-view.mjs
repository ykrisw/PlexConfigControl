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
    <section class="pcc-card">
      <div class="pcc-heading"><h2>${tx('Archive Validation','Weryfikacja archiwum')}</h2>
        <button type="button" data-restore-action="refresh">↻ ${tx('Refresh','Odśwież')}</button></div>
      <p>${tx('Select an archive and start validation before continuing.','Wybierz archiwum i rozpocznij weryfikację przed kontynuowaniem.')}</p>
      <button type="button" class="pcc-primary" data-restore-action="validate" disabled>${tx('Validate Archive','Zweryfikuj archiwum')}</button>
      <div data-validation-progress hidden role="status" aria-live="polite"></div>
      <div data-validation-notice class="pcc-notice" hidden role="status" aria-live="polite"></div>
      <button type="button" data-restore-action="cancel" hidden>${tx('Cancel Restore Preparation','Anuluj przygotowanie przywracania')}</button>
    </section>
    <section data-recovery hidden></section>
    <section class="pcc-card pcc-archive-card"><div class="pcc-heading"><h2>${tx('Select Backup Archive','Wybierz archiwum kopii zapasowej')}</h2></div>
      <div data-archive-list role="group" aria-label="${tx('Backup archives','Archiwa kopii zapasowych')}"></div>
      <p data-archive-message role="status">${tx('Loading archives…','Wczytywanie archiwów…')}</p>
    </section>`;
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
  let selected = null, loading = false, archiveAvailable=false, statusTimer, currentState;

  const render = state => {
    currentState = state;recovery.observe(state.snapshot?.operation);
    selected = state.selected;
    const view=restorePresentation(state,language);
    validate.disabled = view.validateDisabled||loading||!archiveAvailable;
    cancel.hidden = !view.cancelVisible;
    cancel.disabled = view.cancelDisabled;
    for (const input of list.querySelectorAll('input')) {
      input.disabled = view.selectionDisabled||loading||!archiveAvailable;
      input.checked = input.value === selected;
      input.closest('label').classList.toggle('pcc-selected', input.checked);
    }
    notice.textContent = view.notice;
    notice.hidden = !view.notice;
    progress.hidden = !view.progressText;
    progress.textContent = view.progressText;
  };
  const disposeControls = bindRestoreControls(root, client, render);

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
    root.replaceChildren(); root.classList.remove('pcc-restore');
  };
}
