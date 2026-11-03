import {PanelClient} from './panel-client.mjs';
import {mountPanelShell} from './panel-shell.mjs';
import {mountDashboardView} from './dashboard-view.mjs';
import {mountRestoreView} from './restore-view.mjs';
import {mountHistoryView} from './history-view.mjs';
import {mountSettingsView} from './settings-view.mjs';
import {mountBackupView} from './backup-view.mjs';

export function mountPanelApp(root) {
  let epoch = 0, cleanup = () => {}, stopped = false;
  const client = new PanelClient({onSessionExpired: () => showLogin('Sign in required')});
  function reset() { epoch++; cleanup(); cleanup = () => {}; root.replaceChildren(); }
  function showLogin(message = '') {
    if (stopped) return;
    reset(); const generation = epoch;
    root.className = 'pcc-shell'; root.dataset.theme = 'system';
    root.innerHTML = '<header class="pcc-header"><div class="pcc-brand">PlexConfigControl</div></header><form class="pcc-login"><h2>Sign In</h2><label>Password<input name="password" type="password" autocomplete="current-password" required maxlength="4096"></label><p role="alert" class="pcc-notice"></p><button type="submit">Sign In</button></form>';
    const form = root.querySelector('form'), notice = form.querySelector('[role=alert]');
    notice.textContent = message;
    let busy = false;
    const submit = async event => {
      event.preventDefault(); if (busy) return;
      busy = true; const button = form.querySelector('button'); button.disabled = true;
      const input = form.elements.password; const password = input.value; input.value = '';
      try {
        await client.login(password);
        if (epoch === generation && !stopped) await showPanels();
      } catch (error) {
        if (epoch === generation && !stopped) notice.textContent = error.message;
      } finally { busy = false; button.disabled = false; }
    };
    form.addEventListener('submit', submit);
    cleanup = () => { form.removeEventListener('submit', submit); form.reset(); };
  }
  async function showPanels() {
    if (stopped) return;
    const generation = epoch;
    // Preferences must load before revealing protected views. No sample data.
    let prefs;
    try { prefs = await client.settings(); }
    catch (error) { if (epoch === generation) showLogin(error.message); return; }
    if (epoch !== generation || stopped) return;
    reset();
    const viewDisposers = new Map();
    const signedOut = reason => showLogin(reason === 'password_changed' ? 'Password changed. Sign in with your new password.' : '');
    const shell = mountPanelShell(root, {theme: prefs.theme, onNavigate(key, section) {
      if (viewDisposers.has(key)) return;
      if (key === 'dashboard') viewDisposers.set(key, mountDashboardView(section, client, {language: prefs.language, onSignedOut: signedOut}));
      else if (key === 'backup') viewDisposers.set(key,mountBackupView(section,client,{language:prefs.language,timezone:prefs.timezone}));
      else if (key === 'restore') viewDisposers.set(key, mountRestoreView(section, client));
      else if (key === 'history') viewDisposers.set(key, mountHistoryView(section, client, {language:prefs.language,timezone:prefs.timezone}));
      else if (key === 'settings') viewDisposers.set(key,mountSettingsView(section,client,{preferences:prefs,onChanged(next){
        const languageChanged=prefs.language!==next.language;
        prefs=next;shell.setTheme(prefs.theme);shell.setLanguage(prefs.language);
        root.ownerDocument.documentElement.lang=prefs.language;
        if(languageChanged){
          // Dispose only browser views; this never cancels server validation.
          for(const [name,dispose]of viewDisposers){
            if(name!=='settings'){dispose();viewDisposers.delete(name);}
          }
        }
      }}));
      else {
        const card = root.ownerDocument.createElement('section'); card.className = 'pcc-card pcc-fill';
        const text = root.ownerDocument.createElement('p');
        text.textContent = prefs.language === 'pl' ? 'Ten panel wymaga jeszcze podłączenia do funkcji aplikacji.' : 'This panel still needs integration with the application.';
        card.append(text); section.append(card); viewDisposers.set(key, () => section.replaceChildren());
      }
    }});
    shell.setLanguage(prefs.language);
    root.ownerDocument.documentElement.lang = prefs.language;
    cleanup = () => { for (const dispose of viewDisposers.values()) dispose(); shell.dispose(); };
  }
  const initial = epoch;
  void client.restoreSession().then(() => {
    if (!stopped && epoch === initial) return showPanels();
  }).catch(error => { if (!stopped && epoch === initial) showLogin(error.status === 401 ? '' : error.message); });
  return () => { stopped = true; reset(); client.csrf = null; };
}

const root = globalThis.document?.getElementById('pcc-app');
if (root) mountPanelApp(root);
