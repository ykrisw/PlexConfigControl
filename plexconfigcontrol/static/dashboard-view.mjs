import {createDashboardController} from './dashboard-controller.mjs';

export function mountDashboardView(root, client, {onSignedOut, language = 'en'} = {}) {
  const pl = language === 'pl';
  const tx = (en, polish) => pl ? polish : en;
  root.innerHTML = `
    <section class="pcc-plex"><strong data-server></strong><span data-plex-state="UNKNOWN">UNKNOWN</span></section>
    <section class="pcc-card pcc-account">
      <div class="pcc-account-content"><h3 data-account></h3>
        <div class="pcc-avatar" role="img" aria-label="Profile">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 22v-2a8 8 0 0 1 16 0v2"/></svg>
        </div>
        <div class="pcc-account-state"><span data-account-active></span></div>
      </div>
      <div class="pcc-account-actions"><button type="button" data-password></button><button type="button" data-logout></button></div>
    </section>
    <dialog class="pcc-notification-dialog pcc-password-dialog" aria-labelledby="pcc-password-title">
      <form><h3 id="pcc-password-title"></h3>
        <label><span data-current-label></span><input name="current" type="password" autocomplete="current-password" required maxlength="4096"></label>
        <label><span data-new-label></span><input name="password" type="password" autocomplete="new-password" required maxlength="4096"></label>
        <label><span data-confirm-label></span><input name="confirmation" type="password" autocomplete="new-password" required maxlength="4096"></label>
        <p data-password-error role="alert"></p>
        <div class="pcc-dialog-actions"><button type="button" data-close></button><button type="submit" data-save></button></div>
      </form>
    </dialog>
    <p class="pcc-notice" data-dashboard-error role="alert" hidden></p>`;
  const find = selector => root.querySelector(selector);
  const dialog = find('dialog'), form = find('form');
  const lifecycle = new AbortController();
  const labels = {
    '[data-server]': tx('Plex Server', 'Serwer Plex'),
    '[data-account]': tx('Account', 'Konto'),
    '[data-account-active]': tx('ACTIVE', 'AKTYWNE'),
    '[data-password]': tx('Change Password', 'Zmień hasło'),
    '[data-logout]': tx('Log Out', 'Wyloguj'),
    '#pcc-password-title': tx('Change Password', 'Zmień hasło'),
    '[data-current-label]': tx('Current Password', 'Obecne hasło'),
    '[data-new-label]': tx('New Password', 'Nowe hasło'),
    '[data-confirm-label]': tx('Confirm New Password', 'Potwierdź nowe hasło'),
    '[data-close]': tx('Cancel', 'Anuluj'), '[data-save]': tx('Save', 'Zapisz'),
  };
  for (const [selector, label] of Object.entries(labels)) find(selector).textContent = label;
  let busy = false;
  const controller = createDashboardController(client, state => {
    busy = state.busy;
    const status = find('[data-plex-state]');
    status.dataset.plexState = state.plex;
    status.textContent = pl ? ({RUNNING: 'DZIAŁA', STOPPED: 'ZATRZYMANY', UNKNOWN: 'NIEZNANY'}[state.plex]) : state.plex;
    for (const button of root.querySelectorAll('button')) button.disabled = state.busy;
    const error = state.error;
    find('[data-dashboard-error]').hidden = !error || dialog.open;
    find('[data-dashboard-error]').textContent = error;
    find('[data-password-error]').textContent = dialog.open ? error : '';
  }, {onSignedOut});
  const options = {signal: lifecycle.signal};
  find('[data-password]').addEventListener('click', () => {
    form.reset(); find('[data-password-error]').textContent = '';
    find('[data-dashboard-error]').hidden = true;
    dialog.showModal();
  }, options);
  find('[data-close]').addEventListener('click', () => { dialog.close(); form.reset(); }, options);
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); }, options);
  dialog.addEventListener('close', () => form.reset(), options);
  form.addEventListener('submit', event => {
    event.preventDefault();
    const values = new FormData(form);
    void controller.changePassword(values.get('current'), values.get('password'), values.get('confirmation'));
    // Clear password fields immediately; never retain secrets during polling.
    form.reset();
  }, options);
  find('[data-logout]').addEventListener('click', () => void controller.logout(), options);
  return () => {
    lifecycle.abort(); controller.dispose();
    if (dialog.open) dialog.close();
    form.reset(); root.replaceChildren();
  };
}
