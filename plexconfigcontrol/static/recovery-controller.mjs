import {normalizeOutcome} from './operation-outcome.mjs';
// Read-only recovery status. This controller cannot delete snapshots or files.
const archiveName=/^TrueNASPlexConfig_\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2}\.tar\.gz$/;
const temporaryName=/^\.pcc-[0-9a-f]{32}\.tmp$/;
function publication(value){
  if(!value||typeof value.pending!=='boolean')return null;
  const base={pending:value.pending,status:value.status,archive:value.archive,temporary_file:value.temporary_file,replaced_archive:value.replaced_archive??null};
  if(!value.pending&&value.status==='NONE'&&value.archive===null&&value.temporary_file===null&&base.replaced_archive===null)return base;
  if(value.pending&&value.status==='RECORD_UNREADABLE'&&value.archive===null&&value.temporary_file===null&&base.replaced_archive===null)return base;
  if(value.pending&&value.status==='VERIFICATION_REQUIRED'&&typeof value.archive==='string'&&archiveName.test(value.archive)&&
     typeof value.temporary_file==='string'&&temporaryName.test(value.temporary_file)&&
     (base.replaced_archive===null||(typeof base.replaced_archive==='string'&&archiveName.test(base.replaced_archive)&&base.replaced_archive!==value.archive)))return base;
  return null;
}
export function createRecoveryController(client,render,{schedule=setTimeout,cancel=clearTimeout}={}){
  let visible=false,loading=false,disposed=false,data=null,error=false,timer,key='',expected=null,serial=0;
  const lifecycle=new AbortController();
  const emit=()=>{if(!disposed)render({visible,loading,data,error});};
  async function refresh(){
    if(disposed||!visible||loading||!expected)return;
    cancel(timer);loading=true;data=null;error=false;const request=++serial;emit();
    try{
      const result=await client.recovery(lifecycle.signal);
      if(disposed||request!==serial)return;
      const record=publication(result?.publication),outcome=normalizeOutcome(result?.outcome);
      if(!result||result.snapshot_id!==expected.snapshot_id||result.phase!==expected.phase||result.kind!==expected.kind||
         !record||JSON.stringify(record)!==JSON.stringify(expected.publication)||
         outcome===undefined||JSON.stringify(outcome)!==JSON.stringify(expected.outcome)||
         !(expected.snapshot_id===null?result.snapshot_state==='NONE':['PRESENT','ABSENT','UNKNOWN'].includes(result.snapshot_state))||
         result.removal_supported!==false||result.removal_available!==false||result.publication_resolution_supported!==false)
        throw Error('Unverified recovery reply');
      data={...result,publication:record,outcome};
    }catch{if(disposed||request!==serial)return;data=null;error=true;}
    finally{
      if(!disposed&&request===serial){loading=false;emit();if(visible)timer=schedule(refresh,3000);}
    }
  }
  emit();
  return{
    observe(snapshot){
      if(disposed)return;
      const operation=snapshot?.operation;
      if(!operation||!['IDLE','SUCCESS','FAILED','RECOVERY_REQUIRED','VALIDATING','RUNNING','WAITING_FOR_PLEX_STOP','READY'].includes(operation.phase)){if(visible){serial++;key='';expected=null;loading=false;cancel(timer);data=null;error=true;emit();}return;}
      const record=publication(snapshot.publication),outcome=normalizeOutcome(operation.outcome);
      const next=operation.phase==='RECOVERY_REQUIRED'||(['IDLE','SUCCESS','FAILED'].includes(operation.phase)&&snapshot.publication?.pending===true);
      const nextKey=JSON.stringify([operation.phase,operation.kind,operation.snapshot_id,record,outcome]);
      if(nextKey===key)return;
      key=nextKey;serial++;loading=false;cancel(timer);visible=next;data=null;error=next&&(!record||outcome===undefined);
      expected=record&&outcome!==undefined?{phase:operation.phase,kind:operation.kind,snapshot_id:operation.snapshot_id??null,publication:record,outcome}:null;
      emit();if(visible)void refresh();
    },
    refresh,
    dispose(){disposed=true;serial++;lifecycle.abort();cancel(timer);},
  };
}
