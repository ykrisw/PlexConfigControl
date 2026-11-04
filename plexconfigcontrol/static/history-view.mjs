import {createHistoryController} from './history-controller.mjs';

export function mountHistoryView(root, client, {language = 'en', timezone = 'Europe/London'} = {}) {
  const document = root.ownerDocument, pl = language === 'pl';
  const tx = (en, polish) => pl ? polish : en;
  root.classList.add('pcc-history');
  root.innerHTML = `
    <div class="pcc-history-stats">
      <section class="pcc-card"><span data-total-label></span><b data-total>0</b></section>
      <section class="pcc-card"><span data-success-label></span><b data-success>0</b></section>
      <section class="pcc-card"><span data-failed-label></span><b data-failed>0</b></section>
    </div>
    <div class="pcc-history-filters" role="group" aria-label="History filters">
      <button type="button" data-filter="ALL"></button><button type="button" data-filter="BACKUP"></button><button type="button" data-filter="RESTORE"></button>
    </div>
    <section class="pcc-card pcc-events">
      <div class="pcc-heading"><h2 data-heading></h2><div class="pcc-history-actions">
        <button type="button" data-download></button><button type="button" data-clear></button></div></div>
      <p class="pcc-notice" data-notice role="status" aria-live="polite" hidden></p>
      <p data-empty role="status"></p><div class="pcc-scroll-list" data-events></div>
    </section>
    <dialog class="pcc-notification-dialog pcc-password-dialog" aria-label="Confirm history deletion">
      <h3 data-confirm-title></h3><p data-confirm-message></p><p data-selection-count></p>
      <div class="pcc-dialog-actions"><button type="button" data-cancel></button><button type="button" data-confirm></button></div>
    </dialog>`;
  const find = value => root.querySelector(value);
  for (const [selector,text] of Object.entries({
    '[data-total-label]':tx('Total Operations','Wszystkie operacje'),
    '[data-success-label]':tx('Successful','Udane'), '[data-failed-label]':tx('Failed','Nieudane'),
    '[data-heading]':tx('Operations & Events','Operacje i zdarzenia'),
    '[data-download]':tx('Download Logs','Pobierz logi'), '[data-clear]':tx('Clear Selected','Usuń zaznaczone'),
    '[data-confirm-title]':tx('Clear Selected','Usuń zaznaczone'),
    '[data-confirm-message]':tx('Permanently remove the selected web-history records? Files in backup folder/Logs will remain untouched.',
      'Trwale usunąć zaznaczone wpisy historii panelu? Pliki w folderze kopii/Logs pozostaną nietknięte.'),
    '[data-cancel]':tx('Cancel','Anuluj'), '[data-confirm]':tx('Clear Selected','Usuń zaznaczone'),
  })) find(selector).textContent = text;
  const list = find('[data-events]'), dialog = find('dialog');
  const lifecycle = new AbortController();
  let state, confirmation = [], disposed = false;
  const urls = new Map();
  const dateFormat = new Intl.DateTimeFormat(pl ? 'pl-PL' : 'en-GB', {dateStyle:'medium',timeStyle:'medium',timeZone:timezone});
  function render(value) {
    state = value;
    find('[data-total]').textContent = value.counts.all;
    find('[data-success]').textContent = value.counts.success;
    find('[data-failed]').textContent = value.counts.failed;
    const counts = {ALL:value.counts.all,BACKUP:value.counts.backup,RESTORE:value.counts.restore};
    const names = {ALL:tx('All','Wszystkie'),BACKUP:tx('Backup','Kopie'),RESTORE:tx('Restore','Przywracanie')};
    for (const button of root.querySelectorAll('[data-filter]')) {
      button.textContent = `${names[button.dataset.filter]} (${counts[button.dataset.filter]})`;
      button.setAttribute('aria-pressed', String(button.dataset.filter === value.filter));
      button.disabled = value.busy || dialog.open;
    }
    find('[data-download]').disabled = !value.selected.length || value.selected.length > 1000 || value.busy || value.loading || !value.available;
    find('[data-clear]').disabled = !value.selected.length || value.selected.length > 10000 || value.busy || value.loading || !value.available;
    find('[data-cancel]').disabled = value.busy; find('[data-confirm]').disabled = value.busy || value.loading || !value.available;
    const notices = {
      CLEARED: tx('Selected history records removed. Permanent log files were preserved.', 'Usunięto zaznaczone wpisy historii. Trwałe pliki logów zostały zachowane.'),
      CLEAR_UNCONFIRMED: tx('Deletion could not be confirmed. Review the refreshed list before trying again.', 'Nie udało się potwierdzić usunięcia. Przed kolejną próbą sprawdź odświeżoną listę.'),
    };
    const logNotice=value.archiveLogs?.pending>0?
      tx(`Permanent archive-event logs awaiting write: ${value.archiveLogs.pending}. ${value.archiveLogs.enabled?'Check access to backup folder/Logs.':'Archive storage is read-only in this installation.'}`,
         `Trwałe logi zdarzeń archiwów oczekujące na zapis: ${value.archiveLogs.pending}. ${value.archiveLogs.enabled?'Sprawdź dostęp do folderu kopii/Logs.':'Folder archiwów w tej instalacji jest tylko do odczytu.'}`):'';
    const message = value.error || notices[value.notice] || logNotice;
    find('[data-notice]').hidden = !message; find('[data-notice]').textContent = message;
    const empty = find('[data-empty]');
    empty.hidden = Boolean(value.entries.length);
    empty.textContent = value.loading ? tx('Loading history…','Wczytywanie historii…') : value.available ? tx('No events in this view.','Brak zdarzeń w tym widoku.') : tx('History is unavailable.','Historia jest niedostępna.');
    const scroll = list.scrollTop;
    const focusedId = list.contains(document.activeElement) ? document.activeElement.dataset.eventId : null;
    list.replaceChildren();
    for (const event of value.entries) {
      const row = document.createElement('label'); row.className = 'pcc-event-row';
      const input = document.createElement('input'); input.type = 'checkbox';
      input.dataset.eventId = String(event.id); input.checked = value.selected.includes(event.id);
      input.disabled = value.busy || value.loading || !value.available || dialog.open;
      row.classList.toggle('pcc-selected',input.checked);
      const text = document.createElement('span'); text.className = 'pcc-event-text';
      const kind = ({BACKUP:tx('Backup','Kopia zapasowa'),RESTORE:tx('Restore','Przywracanie'),ARCHIVE_DETECTED:tx('Archive detected','Wykryto archiwum')})[event.kind] || String(event.kind);
      let date = String(event.created);
      if (Number.isFinite(Date.parse(event.created))) date = dateFormat.format(new Date(event.created));
      text.textContent = `${date} · ${kind}`;
      if (event.archive) { const archive = document.createElement('small'); archive.textContent = event.archive; text.append(archive); }
      const status = document.createElement('span'); status.className = 'pcc-event-status'; status.dataset.status = event.status;
      status.textContent = ({SUCCESS:tx('SUCCESS','SUKCES'),FAILED:tx('FAILED','BŁĄD'),WARNING:tx('WARNING','OSTRZEŻENIE'),INFO:tx('INFO','INFORMACJA')})[event.status] || String(event.status);
      input.setAttribute('aria-label', `${tx('Select','Zaznacz')}: ${date} · ${kind}`);
      row.append(input,text,status); list.append(row);
      if (input.dataset.eventId === focusedId) input.focus({preventScroll:true});
    }
    list.scrollTop = scroll;
  }
  const controller = createHistoryController(client, render);
  const options = {signal:lifecycle.signal};
  root.addEventListener('change', event => {
    const input = event.target.closest('[data-event-id]');
    if (input) controller.select(Number(input.dataset.eventId),input.checked);
  }, options);
  root.addEventListener('click', event => {
    const filter = event.target.closest('[data-filter]');
    if (filter) controller.setFilter(filter.dataset.filter);
  }, options);
  find('[data-clear]').addEventListener('click', () => {
    confirmation = [...state.selected];
    find('[data-selection-count]').textContent = `${tx('Selected records','Zaznaczone wpisy')}: ${confirmation.length}`;
    dialog.showModal(); render(state);
  }, options);
  dialog.addEventListener('cancel', event => { if (state.busy) event.preventDefault(); }, options);
  dialog.addEventListener('close', () => { confirmation = []; if (!disposed) render(state); }, options);
  find('[data-cancel]').addEventListener('click', () => dialog.close(), options);
  find('[data-confirm]').addEventListener('click', async () => {
    const result = await controller.clear([...confirmation]);
    if (!disposed) { dialog.close(); if (!result) void controller.refresh(); }
  }, options);
  find('[data-download]').addEventListener('click', async () => {
    const result = await controller.download([...state.selected]);
    if (!result || disposed) return;
    const url = URL.createObjectURL(result.blob), link = document.createElement('a');
    link.href = url; link.download = result.filename; link.hidden = true; root.append(link); link.click(); link.remove();
    urls.set(url,setTimeout(() => { URL.revokeObjectURL(url); urls.delete(url); },30000));
  }, options);
  return () => {
    disposed = true; lifecycle.abort(); controller.dispose();
    if (dialog.open) dialog.close();
    for (const [url,timer] of urls) { clearTimeout(timer); URL.revokeObjectURL(url); }
    root.replaceChildren(); root.classList.remove('pcc-history');
  };
}
