import {bindRestoreControls} from './restore-panel.mjs';

// Mount inside the application's main content area, below the five-tab header.
// Archive names, validation results and errors are always inserted as text.
export function mountRestoreView(root, client) {
  root.classList.add('pcc-restore');
  root.innerHTML = `
    <link rel="stylesheet" href="/assets/restore-view.css">
    <section class="pcc-plex" aria-label="Plex status"><strong>Plex Server</strong>
      <span data-plex-state="UNKNOWN">UNKNOWN</span></section>
    <section class="pcc-card">
      <div class="pcc-heading"><h2>Archive Validation</h2>
        <button type="button" data-restore-action="refresh">↻ Refresh</button></div>
      <p>Select an archive and start validation before continuing.</p>
      <button type="button" class="pcc-primary" data-restore-action="validate" disabled>Validate Archive</button>
      <div data-validation-progress hidden role="status" aria-live="polite"></div>
      <div data-validation-notice class="pcc-notice" hidden role="status" aria-live="polite"></div>
      <button type="button" data-restore-action="cancel" hidden>Cancel Restore Preparation</button>
    </section>
    <section class="pcc-card pcc-archive-card"><div class="pcc-heading"><h2>Select Backup Archive</h2></div>
      <div data-archive-list role="group" aria-label="Backup archives"></div>
      <p data-archive-message role="status">Loading archives…</p>
    </section>`;
  const find = selector => root.querySelector(selector);
  const list = find('[data-archive-list]');
  const message = find('[data-archive-message]');
  const notice = find('[data-validation-notice]');
  const progress = find('[data-validation-progress]');
  const validate = find('[data-restore-action="validate"]');
  const cancel = find('[data-restore-action="cancel"]');
  const status = find('[data-plex-state]');
  const lifecycle = new AbortController();
  let selected = null, loading = false, statusTimer, currentState;

  const render = state => {
    currentState = state;
    selected = state.selected;
    const operation = state.snapshot?.operation?.operation;
    const phase = operation?.phase;
    const waiting = ['WAITING_FOR_PLEX_STOP', 'READY'].includes(phase) && operation.kind === 'RESTORE';
    const active = ['VALIDATING', 'RUNNING', 'RECOVERY_REQUIRED'].includes(phase);
    validate.disabled = !selected || state.busy || !operation || waiting || active;
    cancel.hidden = !waiting;
    cancel.disabled = state.busy;
    for (const input of list.querySelectorAll('input')) {
      input.disabled = state.busy || waiting || active;
      input.checked = input.value === selected;
      input.closest('label').classList.toggle('pcc-selected', input.checked);
    }
    const details = operation?.kind === 'RESTORE' ? operation.validation_details : null;
    const readiness = state.snapshot?.readiness;
    let text = state.error || '';
    if (!text && details?.status === 'FAILED') text = details.reason;
    if (!text && details?.status === 'INTERRUPTED') text = details.reason;
    if (!text && phase === 'RECOVERY_REQUIRED') text = 'Recovery or cleanup must be completed before continuing.';
    if (!text && waiting) {
      const reasons = {
        STOP_PLEX_MANUALLY: 'Archive validated. Stop Plex manually in TrueNAS Apps. This panel will wait.',
        PLEX_STOP_NOT_CONFIRMED: 'Plex is not confirmed stopped. Restore remains blocked.',
        ARCHIVE_CHANGED_REVALIDATE: 'The archive changed. Cancel preparation, then validate it again.',
        RECOVERY_REQUIRED: 'Recovery or cleanup is required.',
        VALIDATE_ARCHIVE_FIRST: 'Validate the selected archive before continuing.',
      };
      text = readiness?.ready
        ? 'Archive validated and Plex is stopped. Final Restore execution is not connected in this development build.'
        : reasons[readiness?.reason] || 'Checking Restore readiness…';
    }
    notice.textContent = text;
    notice.hidden = !text;
    const p = state.snapshot?.operation?.progress;
    const showProgress = operation?.kind === 'RESTORE' && phase === 'VALIDATING' && p;
    progress.hidden = !showProgress;
    progress.textContent = showProgress ? `${p.stage.replaceAll('_', ' ')} · ${p.done.toLocaleString()} bytes read · ${Math.floor(p.elapsed_seconds)} s` : '';
  };
  const disposeControls = bindRestoreControls(root, client, render);

  const loadArchives = async () => {
    if (loading) return;
    loading = true;
    try {
      const archives = await client.archives(lifecycle.signal);
      if (lifecycle.signal.aborted) return;
      list.replaceChildren();
      for (const archive of archives) {
        const row = root.ownerDocument.createElement('label');
        row.className = 'pcc-archive-row';
        const input = root.ownerDocument.createElement('input');
        input.type = 'radio'; input.name = 'restore-archive'; input.value = archive.name;
        const content = root.ownerDocument.createElement('span');
        const name = root.ownerDocument.createElement('strong');
        name.textContent = archive.name;
        const size = root.ownerDocument.createElement('small');
        size.textContent = `${(archive.size / 1024 ** 3).toFixed(2)} GiB`;
        content.append(name, size); row.append(input, content); list.append(row);
      }
      message.textContent = archives.length ? '' : 'No backup archives found.';
      message.hidden = Boolean(archives.length);
      if (currentState) render(currentState);
    } catch (error) {
      if (!lifecycle.signal.aborted) { message.hidden = false; message.textContent = error.message; }
    } finally { loading = false; }
  };
  const updatePlex = async () => {
    let value = 'UNKNOWN';
    try {
      const result = await client.status(lifecycle.signal);
      if (['RUNNING', 'STOPPED'].includes(result.state)) value = result.state;
    } catch { /* A failed read must remove any old green/red status. */ }
    if (lifecycle.signal.aborted) return;
    status.dataset.plexState = value; status.textContent = value;
    statusTimer = setTimeout(updatePlex, 2000);
  };
  const refreshArchives = event => {
    if (event.target.closest('[data-restore-action="refresh"]')) void loadArchives();
  };
  root.addEventListener('click', refreshArchives, {signal: lifecycle.signal});
  void loadArchives(); void updatePlex();
  return () => {
    lifecycle.abort(); clearTimeout(statusTimer); disposeControls();
    root.replaceChildren(); root.classList.remove('pcc-restore');
  };
}
