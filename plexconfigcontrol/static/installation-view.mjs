import {createInstallationController} from './installation-controller.mjs';

// Isolated installer component; never mounted in the ordinary five-tab app.
export function mountInstallationView(root,client,{initial,language='en'}={}){
  const tx=(en,pl)=>language==='pl'?pl:en,document=root.ownerDocument;
  root.classList.add('pcc-installer');
  root.innerHTML=`<form data-install-form><h2 data-install-title></h2><div data-install-fields></div>
    <fieldset data-install-manual><legend data-manual-title></legend><label><input type="checkbox" data-manual-mode><span data-manual-label></span></label><label data-manual-path-label><span data-manual-path-title></span><input data-manual-source type="text" autocomplete="off" spellcheck="false"></label></fieldset>
    <section data-install-preview aria-live="polite"><h3 data-preview-title></h3><dl data-preview-paths></dl><p data-preview-note></p></section>
    <section data-install-source hidden><h3 data-source-title></h3><dl data-source-paths></dl></section>
    <p class="pcc-notice" data-install-status role="status" aria-live="polite" hidden></p>
    <div class="pcc-installer-actions"><button type="submit" data-install-check></button><button type="button" data-install-create disabled></button></div></form>
    <dialog class="pcc-notification-dialog" data-install-dialog><h3 data-confirm-title></h3><p data-confirm-description></p><dl data-confirm-paths></dl><div class="pcc-installer-actions"><button type="button" data-install-cancel></button><button type="button" data-install-confirm></button></div></dialog>`;
  const find=selector=>root.querySelector(selector),events=new AbortController(),options={signal:events.signal},controls=new Map();
  const labels={
    '[data-install-title]':tx('Configure backup storage','Konfiguracja miejsca na kopie zapasowe'),
    '[data-manual-title]':tx('Plex configuration source','Źródło konfiguracji Plex'),
    '[data-manual-label]':tx('Enter the Plex configuration path manually','Wpisz ścieżkę konfiguracji Plex ręcznie'),
    '[data-manual-path-title]':tx('Plex configuration path','Ścieżka konfiguracji Plex'),
    '[data-preview-title]':tx('Destination preview','Podgląd miejsca zapisu'),
    '[data-source-title]':tx('Detected Plex source','Potwierdzone źródło Plex'),
    '[data-install-create]':tx('Create backup folder','Utwórz folder kopii'),
    '[data-confirm-title]':tx('Confirm folder creation','Potwierdź utworzenie folderu'),
    '[data-confirm-description]':tx('Create this new folder and its Logs subfolder? Existing folders will not be adopted or have their permissions changed.','Utworzyć ten nowy folder i jego podfolder Logs? Istniejące foldery nie zostaną przejęte ani nie zmienią się ich uprawnienia.'),
    '[data-install-cancel]':tx('Cancel','Anuluj'),
    '[data-install-confirm]':tx('Create folder','Utwórz folder'),
  };
  for(const [selector,text]of Object.entries(labels))find(selector).textContent=text;
  for(const field of initial.fields.filter(field=>['parent','folder_name','archive_prefix'].includes(field.name))){
    const label=document.createElement('label'),span=document.createElement('span'),input=document.createElement('input'),help=document.createElement('small');
    span.textContent=field.label;span.id='pcc-install-label-'+field.name;input.setAttribute('aria-labelledby',span.id);input.type='text';input.name=field.name;input.value=field.value;input.autocomplete='off';input.spellcheck=false;input.required=field.required===true;
    input.maxLength=field.name==='folder_name'?160:field.name==='archive_prefix'?64:4096;
    help.id='pcc-install-help-'+field.name;help.textContent=field.description||'';input.setAttribute('aria-describedby',help.id);
    label.append(span,input,help);find('[data-install-fields]').append(label);controls.set(field.name,input);
  }
  const pairs=(element,rows)=>{element.replaceChildren();for(const [label,value]of rows){const term=document.createElement('dt'),description=document.createElement('dd');term.textContent=label;description.textContent=value;element.append(term,description);}};
  const paths=preview=>[[tx('The folder will be created here:','Folder zostanie utworzony tutaj:'),preview.folder],[tx('Logs:','Logi:'),preview.logs],[tx('Example backup:','Przykładowa kopia:'),preview.archive_path]];
  const dialog=find('[data-install-dialog]');let confirmation=null;
  const messages={
    CHECK_FAILED:tx('The paths could not be checked. Enter the Plex path manually and check again.','Nie udało się sprawdzić ścieżek. Wpisz ścieżkę Plex ręcznie i ponów sprawdzenie.'),
    CREATE_UNCONFIRMED:tx('Folder creation could not be confirmed. Do not repeat it until the installation state and destination have been reviewed.','Nie udało się potwierdzić utworzenia folderu. Nie ponawiaj operacji przed sprawdzeniem stanu instalacji i miejsca zapisu.'),
  };
  const controller=createInstallationController(client,state=>{
    for(const [name,input]of controls){if(input.value!==state.inputs[name])input.value=state.inputs[name];input.disabled=state.busy||['COMPLETE','REVIEW_REQUIRED','CREATE_UNCONFIRMED'].includes(state.phase);}
    find('[data-manual-mode]').checked=state.manual;find('[data-manual-mode]').disabled=state.busy||['COMPLETE','REVIEW_REQUIRED','CREATE_UNCONFIRMED'].includes(state.phase);
    const manual=find('[data-manual-source]');if(manual.value!==(state.inputs.manual_source||''))manual.value=state.inputs.manual_source||'';
    manual.disabled=!state.manual||find('[data-manual-mode]').disabled;find('[data-manual-path-label]').hidden=!state.manual;
    const preview=find('[data-install-preview]');preview.hidden=!state.preview;
    if(state.preview){pairs(find('[data-preview-paths]'),paths(state.preview));find('[data-preview-note]').textContent=state.preview.created?tx('Folder created. The archive name is an example; no backup has been performed.','Folder został utworzony. Nazwa archiwum jest przykładem; kopia nie została jeszcze wykonana.'):state.preview.checked?tx('Paths checked. The folder has not been created yet. The archive name is an example.','Ścieżki sprawdzone. Folder nie został jeszcze utworzony. Nazwa archiwum jest przykładem.'):tx('Preview only. Check these paths before creating the folder.','To podgląd. Sprawdź ścieżki przed utworzeniem folderu.');}
    find('[data-install-source]').hidden=!state.storage;
    if(state.storage)pairs(find('[data-source-paths]'),[[tx('Storage type','Rodzaj magazynu'),({ix_volume:'ixVolume',host_path:'Host Path',manual:tx('Manual path','Ścieżka ręczna')})[state.storage.type]||state.storage.type],[tx('Configuration path','Ścieżka konfiguracji'),state.storage.source],[tx('Dataset','Dataset'),state.storage.dataset]]);
    find('[data-install-check]').disabled=!state.canCheck;find('[data-install-check]').textContent=state.phase==='CHECKING'?tx('Checking…','Sprawdzanie…'):tx('Check settings','Sprawdź ustawienia');
    find('[data-install-create]').disabled=!state.canCreate;
    const status=state.error||messages[state.notice]||(state.phase==='CREATING'?tx('Creating folder…','Tworzenie folderu…'):state.phase==='COMPLETE'?tx('Backup storage configured. No backup has been performed.','Miejsce na kopie zostało skonfigurowane. Nie wykonano jeszcze kopii zapasowej.'):state.phase==='REVIEW_REQUIRED'?messages.CREATE_UNCONFIRMED:'');
    find('[data-install-status]').textContent=status;find('[data-install-status]').hidden=!status;
    find('[data-install-confirm]').disabled=state.busy;find('[data-install-cancel]').disabled=state.busy;
    if(dialog.open&&!['READY','CREATING'].includes(state.phase)){dialog.close();confirmation=null;}
  },{initial});
  for(const [name,input]of controls)input.addEventListener('input',()=>controller.edit(name,input.value),options);
  find('[data-manual-source]').addEventListener('input',event=>controller.edit('manual_source',event.target.value),options);
  find('[data-manual-mode]').addEventListener('change',event=>controller.manual(event.target.checked),options);
  find('[data-install-form]').addEventListener('submit',event=>{event.preventDefault();void controller.check();},options);
  find('[data-install-create]').addEventListener('click',()=>{confirmation=controller.confirmation();if(!confirmation)return;pairs(find('[data-confirm-paths]'),[[tx('Folder','Folder'),confirmation.folder],[tx('Logs','Logi'),confirmation.logs],[tx('Archive prefix','Początek nazwy archiwum'),confirmation.prefix]]);dialog.showModal();},options);
  find('[data-install-cancel]').addEventListener('click',()=>{confirmation=null;dialog.close();},options);
  find('[data-install-confirm]').addEventListener('click',()=>{void controller.create(confirmation);},options);
  dialog.addEventListener('cancel',event=>{if(find('[data-install-confirm]').disabled)event.preventDefault();else confirmation=null;},options);
  return()=>{controller.dispose();events.abort();if(dialog.open)dialog.close();root.replaceChildren();};
}
