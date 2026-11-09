// Immutable request identity survives uncertain replies within this view.
// Status checks are read-only; resubmission is always an explicit user action.
const states=new Set(['QUEUED','RUNNING','SUCCEEDED','FAILED','RECOVERY_REQUIRED']);
export function createSubmission(send,read,changed,{kind,makeId=()=>globalThis.crypto.randomUUID().replaceAll('-','')}={}){
  let pending=null,phase='IDLE',busy=false,checking=false,disposed=false,generation=0,observation=0;
  const lifecycle=new AbortController();
  const view=()=>({phase,busy,checking,request_id:pending?.request_id??null,
    archive:typeof pending?.archive==='string'?pending.archive:pending?.archive?.name??null,action:pending?.mode??null,
    blocked:busy||['SENDING','ACCEPTED','UNCONFIRMED','QUEUED','RUNNING','RECOVERY_REQUIRED'].includes(phase),
    canRetry:phase==='UNCONFIRMED'&&!busy&&!checking,
    canCheck:pending!==null&&!busy&&!checking&&['ACCEPTED','UNCONFIRMED','QUEUED','RUNNING'].includes(phase)});
  const emit=()=>{if(!disposed)changed(view());};
  function observe(job){
    if(disposed||!pending||job?.request_id!==pending.request_id||job.kind!==kind||!states.has(job.state))return false;
    if(['SUCCEEDED','FAILED'].includes(phase)&&phase!==job.state)return true;
    if(phase==='RECOVERY_REQUIRED'&&job.state!=='FAILED'&&job.state!=='RECOVERY_REQUIRED')return true;
    observation++;if(phase!==job.state){phase=job.state;emit();}return true;
  }
  async function attempt(){
    if(disposed||busy||!pending)return false;
    const serial=generation,identity=pending.request_id;busy=true;phase='SENDING';emit();
    try{
      const receipt=await send(structuredClone(pending),lifecycle.signal);
      if(disposed||generation!==serial)return false;
      if(receipt?.accepted!==true||receipt.request_id!==identity||receipt.kind!==kind||receipt.status_url!=='/api/operation')throw Error('Unconfirmed receipt');
      // A read-only poll may already have confirmed the same job's outcome.
      if(phase==='SENDING')phase='ACCEPTED';return true;
    }catch(error){
      if(!disposed&&generation===serial&&phase==='SENDING')phase=[400,401,403,409,422].includes(error.status)?'REJECTED':'UNCONFIRMED';
      return false;
    }finally{if(generation===serial)busy=false;emit();}
  }
  return{
    view,observe,
    async submit(payload){
      if(disposed||view().blocked)return false;
      let request_id,next;
      try{request_id=makeId();if(!/^[0-9a-f]{32}$/.test(request_id))throw Error('Invalid identity');next={...structuredClone(payload),request_id};}
      catch{phase='REJECTED';emit();return false;}
      generation++;checking=false;pending=next;return attempt();
    },
    retry(){return view().canRetry?attempt():Promise.resolve(false);},
    async check(){
      if(!view().canCheck||disposed)return false;
      const serial=generation,identity=pending.request_id,seen=observation;checking=true;emit();
      try{
        const result=await read(identity,lifecycle.signal);
        if(disposed||serial!==generation||seen!==observation)return false;
        if(result?.found===true&&observe(result.execution))return true;
        phase='UNCONFIRMED';return false; // Absence now is not proof an earlier POST cannot finish later.
      }catch{if(!disposed&&serial===generation&&seen===observation)phase='UNCONFIRMED';return false;}
      finally{if(serial===generation)checking=false;emit();}
    },
    dispose(){disposed=true;generation++;pending=null;lifecycle.abort();},
  };
}
export function submissionText(value,language='en',kind){
  const pl=language==='pl',tx=(en,polish)=>pl?polish:en;
  const text=({SENDING:tx('Submitting confirmed operation…','Przekazywanie potwierdzonej operacji…'),
    ACCEPTED:tx('Operation accepted. Waiting for its status.','Operacja przyjęta. Oczekiwanie na jej stan.'),
    UNCONFIRMED:tx('Submission could not be confirmed. Check its status or explicitly retry the same request.','Nie potwierdzono przyjęcia zlecenia. Sprawdź jego stan lub świadomie ponów to samo żądanie.'),
    QUEUED:tx('Operation admitted and awaiting execution.','Operacja przyjęta i oczekuje na wykonanie.'),
    RUNNING:kind==='BACKUP'
      ?tx('Backup is in progress. Wait for verification to finish.','Trwa wykonywanie kopii zapasowej. Poczekaj do końca weryfikacji.')
      :tx('Operation is running. You may leave this tab.','Operacja trwa. Możesz opuścić tę zakładkę.'),
    REJECTED:tx('Operation was not accepted. Refresh and confirm the current selection again.','Operacja nie została przyjęta. Odśwież i ponownie potwierdź aktualny wybór.'),
    FAILED:tx('Operation failed. Review History and recovery details.','Operacja nie powiodła się. Sprawdź Historię i szczegóły odzyskiwania.'),
    RECOVERY_REQUIRED:tx('Operation requires recovery or cleanup before continuing.','Operacja wymaga odzyskiwania lub sprzątania przed kontynuowaniem.'),
    SUCCEEDED:tx('Operation completed. Verified details are shown in the result and History.','Operacja zakończona. Zweryfikowane szczegóły znajdziesz w wyniku i Historii.'),
  })[value?.phase]||'';
  return text&&typeof value?.archive==='string'?text+' '+tx('Archive: ','Archiwum: ')+value.archive:text;
}
