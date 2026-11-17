// Installer-only controller. The embedding host supplies a trusted adapter;
// this module never chooses a URL, API method, dataset or privileged command.
const editable=['parent','folder_name','archive_prefix','manual_source'];
const terminal=new Set(['COMPLETE','REVIEW_REQUIRED','CREATE_UNCONFIRMED']);
const normalized=value=>'/'+value.split('/').filter(part=>part&&part!=='.').join('/');
export function installationPreview(inputs,instant=new Date()){
  const parent=inputs.parent,folder=inputs.folder_name||'Plex Backup',prefix=inputs.archive_prefix||'PlexConfig';
  if(typeof parent!=='string'||!parent.startsWith('/')||parent.startsWith('//')||parent.split('/').includes('..')||/[\x00-\x1f\\]/.test(parent)||normalized(parent)==='/')return null;
  if(typeof folder!=='string'||![...folder].length||[...folder].length>80||new TextEncoder().encode(folder).length>200||folder.trim()!==folder||folder.endsWith('.')||['.','..'].includes(folder)||/[\x00-\x1f/\\:<>"|?*]/.test(folder)||/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(folder)||[...folder].some(c=>c.codePointAt(0)>=0xd800&&c.codePointAt(0)<=0xdfff))return null;
  if(typeof prefix!=='string'||!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(prefix)||!Number.isFinite(instant.getTime()))return null;
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(instant).map(part=>[part.type,part.value]));
  const root=normalized(parent)+'/'+folder,name=`${prefix}_${parts.year}.${parts.month}.${parts.day}_${parts.hour}.${parts.minute}.${parts.second}.tar.gz`;
  return{folder:root,logs:root+'/Logs',archive:name,archive_path:root+'/'+name,example:true,checked:false,created:false};
}

export function createInstallationController(client,render,{initial,now=()=>new Date()}={}){
  if(!initial||initial.phase!=='UNVERIFIED'||!Array.isArray(initial.fields))throw Error('A fresh trusted installer model is required');
  const inputs={parent:'',folder_name:'Plex Backup',archive_prefix:'PlexConfig',manual_source:null};
  for(const field of initial.fields)if(editable.includes(field.name)&&typeof field.value==='string')inputs[field.name]=field.value;
  let disposed=false,generation=0,read=null,revision=null,attempted=new Set();
  const state={phase:'UNVERIFIED',inputs,preview:installationPreview(inputs,now()),manual:false,busy:false,error:null,notice:'',storage:null};
  const emit=()=>{if(!disposed)render({...state,inputs:{...inputs},preview:state.preview?{...state.preview}:null,storage:state.storage?{...state.storage}:null,canCheck:!state.busy&&!terminal.has(state.phase)&&Boolean(state.preview)&&(!state.manual||Boolean(inputs.manual_source)),canCreate:!state.busy&&state.phase==='READY'&&revision!==null});};
  function invalidate(){generation++;read?.abort();read=null;revision=null;state.phase='UNVERIFIED';state.storage=null;state.error=null;state.notice='';state.preview=installationPreview(inputs,now());emit();}
  const payload=()=>({...inputs,manual_source:state.manual?inputs.manual_source:null});
  function matches(model){const expected=installationPreview(inputs,now()),storage=model?.storage;return expected&&storage&&storage.output===expected.folder&&storage.folder_name===(inputs.folder_name||'Plex Backup')&&storage.archive_prefix===(inputs.archive_prefix||'PlexConfig')&&storage.logs_folder==='Logs';}
  function apply(model){
    if(!model||!['UNVERIFIED','MANUAL_REQUIRED','RENAME_REQUIRED','READY','COMPLETE','REVIEW_REQUIRED'].includes(model.phase))throw Error('Invalid installer response');
    if((model.phase==='READY'||model.phase==='COMPLETE')&&!matches(model))throw Error('Installer paths changed');
    if(model.phase==='READY'&&(!/^[a-f0-9]{32}$/.test(model.revision)||model.can_create!==true||attempted.has(model.revision)))throw Error('Invalid checked plan');
    state.phase=model.phase;state.error=model.error&&typeof model.error.message==='string'?model.error.message:null;
    state.storage=model.storage?{...model.storage}:null;revision=model.phase==='READY'?model.revision:null;
    state.preview=installationPreview(inputs,now());
    if(state.preview){state.preview.checked=['READY','COMPLETE'].includes(model.phase);state.preview.created=model.phase==='COMPLETE';}
    if(model.phase==='MANUAL_REQUIRED')state.manual=true;
  }
  emit();
  return{
    edit(name,value){if(disposed||state.busy||terminal.has(state.phase)||!editable.includes(name)||typeof value!=='string')return;inputs[name]=value;invalidate();},
    manual(enabled){if(disposed||state.busy||terminal.has(state.phase)||typeof enabled!=='boolean')return;state.manual=enabled;invalidate();},
    async check(){
      if(disposed||state.busy||terminal.has(state.phase)||!state.preview||(state.manual&&!inputs.manual_source))return false;
      revision=null;state.storage=null;state.error=null;state.notice='';if(state.preview)state.preview.checked=false;state.busy=true;state.phase='CHECKING';const current=++generation;read=new AbortController();emit();
      try{const model=await client.check(payload(),read.signal);if(disposed||current!==generation)return false;apply(model);return state.phase==='READY';}
      catch{if(!disposed&&current===generation){state.phase='MANUAL_REQUIRED';state.manual=true;state.error=null;state.notice='CHECK_FAILED';revision=null;}return false;}
      finally{if(!disposed&&current===generation){read=null;state.busy=false;emit();}}
    },
    confirmation(){return !disposed&&!state.busy&&state.phase==='READY'&&revision?Object.freeze({revision,folder:state.preview.folder,logs:state.preview.logs,prefix:inputs.archive_prefix||'PlexConfig'}):null;},
    async create(confirmation){
      if(disposed||state.busy||state.phase!=='READY'||!confirmation||confirmation.revision!==revision||confirmation.folder!==state.preview?.folder||confirmation.logs!==state.preview?.logs||confirmation.prefix!==(inputs.archive_prefix||'PlexConfig')||attempted.has(revision))return false;
      const identifier=revision;attempted.add(identifier);revision=null;state.busy=true;state.error=null;state.notice='';state.phase='CREATING';emit();
      try{
        // No AbortController for a write: leaving this view does not undo it.
        const model=await client.create({revision:identifier,confirmed:true});
        if(disposed)return false;
        if(!['COMPLETE','REVIEW_REQUIRED','RENAME_REQUIRED','MANUAL_REQUIRED'].includes(model?.phase))throw Error('Creation not confirmed');
        apply(model);return state.phase==='COMPLETE';
      }catch{if(!disposed){state.phase='CREATE_UNCONFIRMED';state.notice='CREATE_UNCONFIRMED';state.storage=null;if(state.preview)state.preview.checked=false;}return false;}
      finally{if(!disposed){state.busy=false;emit();}}
    },
    dispose(){disposed=true;generation++;read?.abort();read=null;revision=null;},
  };
}
