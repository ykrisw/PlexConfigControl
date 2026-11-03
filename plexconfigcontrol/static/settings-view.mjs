import {mountIntegrationView} from './integration-view.mjs';
import {createSettingsController} from './settings-controller.mjs';

export function mountSettingsView(root,client,{preferences,onChanged}={}) {
  root.classList.add('pcc-settings');
  root.innerHTML=`
    <section class="pcc-card pcc-language"><strong data-language-label></strong>
      <select data-language aria-label="Language"><option value="en">English</option><option value="pl">Polski</option></select></section>
    <section class="pcc-card pcc-appearance"><h2 class="pcc-section-title" data-appearance></h2>
      <div class="pcc-theme-row"><strong data-theme-label></strong><div class="pcc-theme-buttons" role="group" aria-label="Theme">
        <button type="button" data-theme-choice="Light"></button><button type="button" data-theme-choice="Dark"></button><button type="button" data-theme-choice="System"></button>
      </div></div><p data-settings-notice class="pcc-notice" role="status" aria-live="polite" hidden></p></section>
    <section class="pcc-card pcc-about"><h2 class="pcc-section-title" data-about></h2><div class="pcc-about-info">
      <div class="pcc-about-row"><span data-application-label></span><span>PlexConfigControl</span></div>
      <div class="pcc-about-row"><span data-version-label></span><span data-version></span></div>
      <div class="pcc-about-row"><span data-created-label></span><span class="pcc-author">Krzysztof Wojciechowski</span></div>
      <details><summary data-details-label></summary><p data-details></p><section data-integration></section></details>
    </div></section>`;
  const find=selector=>root.querySelector(selector);
  const lifecycle=new AbortController();
  const integration=mountIntegrationView(find('[data-integration]'),client,{language:preferences.language});
  const controller=createSettingsController(client,preferences,state=>{
    integration.setLanguage(state.preferences.language);
    const pl=state.preferences.language==='pl';const tx=(en,polish)=>pl?polish:en;
    const labels={
      '[data-language-label]':tx('Language','Język'),'[data-appearance]':tx('Appearance','Wygląd'),
      '[data-theme-label]':tx('Theme','Motyw'),'[data-about]':tx('About','O aplikacji'),
      '[data-application-label]':tx('Application','Aplikacja'),'[data-version-label]':tx('Version','Wersja'),
      '[data-version]':tx('Development preview','Wersja rozwojowa'),'[data-created-label]':tx('Created by','Autor'),
      '[data-details-label]':tx('Details','Szczegóły'),
      '[data-details]':tx('PlexConfigControl is designed for installation as a TrueNAS SCALE App, with application settings stored in an iXVolume. Installers for other platforms may be developed in future versions. Test build: backup creation and restore execution are unavailable.','PlexConfigControl jest przeznaczony do instalacji jako aplikacja TrueNAS SCALE, z ustawieniami programu przechowywanymi w iXVolume. W przyszłości mogą powstać instalatory dla innych platform. Wersja testowa: tworzenie kopii i wykonywanie przywracania są niedostępne.'),
    };
    for(const [selector,label]of Object.entries(labels))find(selector).textContent=label;
    const language=find('[data-language]');language.value=state.preferences.language;language.disabled=state.busy;
    for(const button of root.querySelectorAll('[data-theme-choice]')){
      button.disabled=state.busy;
      const theme=button.dataset.themeChoice;
      button.textContent=({Light:tx('Light','Jasny'),Dark:tx('Dark','Ciemny'),System:tx('System','Systemowy')})[theme];
      button.setAttribute('aria-pressed',String(theme===state.preferences.theme));
    }
    const notice=find('[data-settings-notice]');
    notice.hidden=!state.error&&!state.saved;
    notice.textContent=state.error?tx('Settings could not be confirmed. Try again or reload the page.','Nie udało się potwierdzić ustawień. Spróbuj ponownie lub odśwież stronę.'):
      state.saved?tx('Settings saved.','Ustawienia zapisane.'):'';
  },onChanged);
  root.addEventListener('click',event=>{
    const button=event.target.closest('[data-theme-choice]');
    if(button)void controller.save('theme',button.dataset.themeChoice);
  },{signal:lifecycle.signal});
  find('[data-language]').addEventListener('change',event=>void controller.save('language',event.target.value),{signal:lifecycle.signal});
  return()=>{lifecycle.abort();controller.dispose();integration.dispose();root.replaceChildren();root.classList.remove('pcc-settings');};
}
