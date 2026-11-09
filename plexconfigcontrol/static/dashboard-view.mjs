import {createDashboardController} from './dashboard-controller.mjs';
import {createPhotoController} from './photo-controller.mjs';

export function mountDashboardView(root, client, {onSignedOut, language = 'en'} = {}) {
  const pl = language === 'pl';
  const tx = (en, polish) => pl ? polish : en;
  root.innerHTML = `
    <section class="pcc-plex"><strong data-server></strong><span data-plex-state="UNKNOWN">UNKNOWN</span></section>
    <section class="pcc-card pcc-account">
      <div class="pcc-account-content"><h3 data-account></h3>
        <div class="pcc-avatar" role="group" aria-label="${tx('Profile photo','Zdjęcie konta')}">
          <svg data-photo-placeholder viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 22v-2a8 8 0 0 1 16 0v2"/></svg>
          <img data-profile-photo alt="${tx('Profile photo','Zdjęcie konta')}" draggable="false" hidden>
          <div class="pcc-photo-tools">
            <button type="button" data-photo-upload aria-label="Upload Photo"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="m3 17 6-6 4 4 3-3 5 5M14 7h4m-2-2v4"/></svg></button>
            <button type="button" data-photo-remove aria-label="Remove Photo"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/></svg></button>
          </div>
        </div>
        <input data-photo-file type="file" accept="image/jpeg,image/png" hidden>
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
    <dialog data-photo-dialog class="pcc-notification-dialog pcc-password-dialog" aria-label="Remove Photo">
      <h3 data-photo-title></h3><p data-photo-question></p><div class="pcc-dialog-actions"><button type="button" data-photo-cancel></button><button type="button" data-photo-confirm></button></div>
    </dialog>
    <p data-photo-notice class="pcc-notice" role="alert" hidden></p>
    <p class="pcc-notice" data-dashboard-error role="alert" hidden></p>`;
  const find = selector => root.querySelector(selector);
  const dialog = find('dialog'), form = find('form'), photoDialog=find('[data-photo-dialog]');
  const lifecycle = new AbortController();
  const labels = {
    '[data-server]': tx('Plex Server', 'Serwer Plex'),
    '[data-account]': tx('Account', 'Konto'),
    '[data-password]': tx('Change Password', 'Zmień hasło'),
    '[data-logout]': tx('Log Out', 'Wyloguj'),
    '#pcc-password-title': tx('Change Password', 'Zmień hasło'),
    '[data-current-label]': tx('Current Password', 'Obecne hasło'),
    '[data-new-label]': tx('New Password', 'Nowe hasło'),
    '[data-confirm-label]': tx('Confirm New Password', 'Potwierdź nowe hasło'),
    '[data-close]': tx('Cancel', 'Anuluj'), '[data-save]': tx('Save', 'Zapisz'),
    '[data-photo-title]':tx('Remove Photo','Usuń zdjęcie'),
    '[data-photo-question]':tx('Remove the profile photo from this account?','Usunąć zdjęcie z tego konta?'),
    '[data-photo-cancel]':tx('Cancel','Anuluj'),'[data-photo-confirm]':tx('Remove','Usuń'),
  };
  for (const [selector, label] of Object.entries(labels)) find(selector).textContent = label;
  find('[data-photo-upload]').setAttribute('aria-label',tx('Upload or Replace Photo','Dodaj lub zastąp zdjęcie'));
  find('[data-photo-remove]').setAttribute('aria-label',tx('Remove Photo','Usuń zdjęcie'));
  let busy = false,accountBusy=false,photoState={busy:false,loading:true,present:false},shownRevision=null;
  function updateActions(){
    busy=accountBusy||photoState.busy;
    for(const button of root.querySelectorAll('button'))button.disabled=busy;
    find('[data-photo-upload]').disabled=busy||photoState.loading;
    find('[data-photo-remove]').disabled=busy||photoState.loading||!photoState.present;
  }
  const controller = createDashboardController(client, state => {
    accountBusy = state.busy;
    const status = find('[data-plex-state]');
    status.dataset.plexState = state.plex;
    status.textContent = pl ? ({RUNNING: 'DZIAŁA', STOPPED: 'ZATRZYMANY', UNKNOWN: 'NIEZNANY'}[state.plex]) : state.plex;
    updateActions();
    const error = state.error;
    find('[data-dashboard-error]').hidden = !error || dialog.open;
    find('[data-dashboard-error]').textContent = error;
    find('[data-password-error]').textContent = dialog.open ? error : '';
  }, {onSignedOut});
  const image=find('[data-profile-photo]'),placeholder=find('[data-photo-placeholder]');
  const photoController=createPhotoController(client,state=>{
    photoState=state;updateActions();
    image.hidden=!state.present;placeholder.toggleAttribute('hidden',state.present);
    if(state.present&&state.revision!==shownRevision){shownRevision=state.revision;image.src='/api/account/photo?revision='+state.revision;}
    if(!state.present){shownRevision=null;image.removeAttribute('src');}
    const errors={
      'Choose a JPEG or PNG photo up to 5 MiB':'Wybierz zdjęcie JPEG lub PNG o rozmiarze do 5 MiB.',
      'Photo exceeds the 20 megapixel limit':'Zdjęcie przekracza limit 20 megapikseli.',
      'Animated profile photos are not supported':'Animowane zdjęcia konta nie są obsługiwane.',
      'Photo is corrupt or is not a supported JPEG/PNG image':'Zdjęcie jest uszkodzone lub nie jest obsługiwanym obrazem JPEG/PNG.',
      'Profile photo storage is unavailable':'Magazyn zdjęcia konta jest niedostępny.',
      'Profile photo changed. Reload before removing it.':'Zdjęcie zmieniło się. Odśwież stronę przed jego usunięciem.',
    };
    find('[data-photo-notice]').hidden=!state.error;
    find('[data-photo-notice]').textContent=pl?(errors[state.error]||state.error):state.error;
  });
  const options = {signal: lifecycle.signal};
  const avatar = find('.pcc-avatar'), photoTools = find('.pcc-photo-tools');
  let photoPress = null;
  function cancelPhotoPress() {
    if (!photoPress) return;
    clearTimeout(photoPress.timer);
    photoPress = null;
  }
  function hidePhotoTools() {
    cancelPhotoPress();
    avatar.removeAttribute('data-photo-tools-open');
  }
  avatar.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'touch') return;
    avatar.setAttribute('data-photo-touch', '');
    if (avatar.hasAttribute('data-photo-tools-open') && photoTools.contains(event.target)) return;
    hidePhotoTools();
    if (!event.isPrimary) return;
    photoPress = {
      id: event.pointerId, x: event.clientX, y: event.clientY,
      timer: setTimeout(() => avatar.setAttribute('data-photo-tools-open', ''), 3000),
    };
  }, options);
  avatar.addEventListener('pointermove', event => {
    if (event.pointerType === 'mouse') {
      hidePhotoTools();
      avatar.removeAttribute('data-photo-touch');
    } else if (event.pointerId === photoPress?.id &&
               Math.hypot(event.clientX - photoPress.x, event.clientY - photoPress.y) > 10) {
      cancelPhotoPress();
    }
  }, options);
  avatar.addEventListener('pointerup', event => {
    if (event.pointerId === photoPress?.id) cancelPhotoPress();
  }, options);
  avatar.addEventListener('pointercancel', event => {
    if (event.pointerId === photoPress?.id) hidePhotoTools();
  }, options);
  avatar.addEventListener('contextmenu', event => {
    if (avatar.hasAttribute('data-photo-touch')) event.preventDefault();
  }, options);
  photoTools.addEventListener('click', event => {
    if (avatar.hasAttribute('data-photo-touch') && !avatar.hasAttribute('data-photo-tools-open')) {
      event.preventDefault();
      event.stopPropagation();
    }
  }, {...options, capture: true});
  root.ownerDocument.addEventListener('pointerdown', event => {
    if (!avatar.contains(event.target)) hidePhotoTools();
  }, options);
  lifecycle.signal.addEventListener('abort', cancelPhotoPress, {once: true});
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
  image.addEventListener('error',()=>{image.hidden=true;placeholder.removeAttribute('hidden');
    find('[data-photo-notice]').hidden=false;find('[data-photo-notice]').textContent=tx('The profile photo could not be loaded. Try uploading it again.','Nie udało się wczytać zdjęcia konta. Spróbuj wgrać je ponownie.');},options);
  const file=find('[data-photo-file]');
  find('[data-photo-upload]').addEventListener('click',()=>{file.click();hidePhotoTools();},options);
  file.addEventListener('change',()=>{const chosen=file.files[0];file.value='';if(chosen)void photoController.upload(chosen);},options);
  find('[data-photo-remove]').addEventListener('click',()=>{photoDialog.showModal();hidePhotoTools();},options);
  find('[data-photo-cancel]').addEventListener('click',()=>photoDialog.close(),options);
  photoDialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();},options);
  find('[data-photo-confirm]').addEventListener('click',async()=>{
    await photoController.remove(true);if(!lifecycle.signal.aborted)photoDialog.close();
  },options);
  return () => {
    lifecycle.abort(); controller.dispose();photoController.dispose();file.value='';image.removeAttribute('src');
    if (dialog.open) dialog.close();
    if(photoDialog.open)photoDialog.close();
    form.reset(); root.replaceChildren();
  };
}
