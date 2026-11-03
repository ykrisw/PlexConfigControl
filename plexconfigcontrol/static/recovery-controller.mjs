// Read-only recovery status. This controller cannot delete snapshots or files.
export function createRecoveryController(client,render,{schedule=setTimeout,cancel=clearTimeout}={}){
  let visible=false,loading=false,disposed=false,data=null,error=false,timer,key='',expected=null,serial=0;
  const lifecycle=new AbortController();
  const emit=()=>{if(!disposed)render({visible,loading,data,error});};
  async function refresh(){
    if(disposed||!visible||loading)return;
    cancel(timer);loading=true;data=null;error=false;const request=++serial;emit();
    try{
      const result=await client.recovery(lifecycle.signal);
      if(disposed||request!==serial)return;
      if(!result||result.snapshot_id!==expected||result.phase!=='RECOVERY_REQUIRED'||
         !(expected===null?result.snapshot_state==='NONE':['PRESENT','ABSENT','UNKNOWN'].includes(result.snapshot_state))||
         result.removal_supported!==false||result.removal_available!==false)
        throw Error('Unverified recovery reply');
      data=result;
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
      if(!operation||!['IDLE','SUCCESS','FAILED','RECOVERY_REQUIRED','VALIDATING','RUNNING','WAITING_FOR_PLEX_STOP','READY'].includes(operation.phase)){if(visible){serial++;key='';loading=false;cancel(timer);data=null;error=true;emit();}return;}
      const next=operation.phase==='RECOVERY_REQUIRED';
      const nextKey=JSON.stringify([operation.phase,operation.kind,operation.snapshot_id,snapshot.publication]);
      if(nextKey===key)return;
      key=nextKey;serial++;loading=false;cancel(timer);visible=next;data=null;error=false;expected=operation.snapshot_id??null;
      emit();if(visible)void refresh();
    },
    refresh,
    dispose(){disposed=true;serial++;lifecycle.abort();cancel(timer);},
  };
}
