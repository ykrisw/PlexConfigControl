// Explicit read-only diagnostics. No timers, automatic probes or host mutations.
const member=(value,choices)=>choices.includes(value);
function checked(value){
  if(!value||value.schema!==1||typeof value.checked_at!=='string'||!Number.isFinite(Date.parse(value.checked_at))||
     value.backup_available!==false||value.restore_available!==false||value.execution_reason!=='HOST_EXECUTION_NOT_CONNECTED')return null;
  const {plex,archives,snapshot,operation}=value;
  if(!plex||typeof plex.configured!=='boolean'||!member(plex.state,['NOT_CHECKED','NOT_CONFIGURED','READ_VERIFIED','UNAVAILABLE'])||
     !member(plex.app_state,['UNKNOWN','RUNNING','STOPPED','STOPPING','DEPLOYING','CRASHED'])||
     (plex.state==='READ_VERIFIED'&&(!plex.configured||plex.app_state==='UNKNOWN'))||
     (plex.state!=='READ_VERIFIED'&&plex.app_state!=='UNKNOWN'))return null;
  if(!archives||typeof archives.configured!=='boolean'||!member(archives.state,['NOT_CHECKED','NOT_CONFIGURED','LIST_VERIFIED','UNAVAILABLE'])||
     (archives.state==='LIST_VERIFIED'?(!archives.configured||!Number.isSafeInteger(archives.count)||archives.count<0):archives.count!==null))return null;
  if(!snapshot||typeof snapshot.configured!=='boolean'||!member(snapshot.state,['NOT_CHECKED','NOT_CONFIGURED','NO_RECORDED_SNAPSHOT','PRESENT','ABSENT','UNKNOWN'])||
     (['PRESENT','ABSENT','NO_RECORDED_SNAPSHOT'].includes(snapshot.state)&&!snapshot.configured))return null;
  if(!operation||!member(operation.state,['UNKNOWN','BUSY','CHANGED','RECOVERY_REQUIRED','ACTIVE','WAITING_FOR_USER','IDLE'])||
     !(operation.phase===null||member(operation.phase,['IDLE','SUCCESS','FAILED','RECOVERY_REQUIRED','VALIDATING','RUNNING','WAITING_FOR_PLEX_STOP','READY'])))return null;
  return{schema:1,checked_at:value.checked_at,backup_available:false,restore_available:false,
    execution_reason:'HOST_EXECUTION_NOT_CONNECTED',plex:{configured:plex.configured,state:plex.state,app_state:plex.app_state},
    archives:{configured:archives.configured,state:archives.state,count:archives.count},
    snapshot:{configured:snapshot.configured,state:snapshot.state},operation:{state:operation.state,phase:operation.phase}};
}
export function createIntegrationController(client,render){
  let disposed=false,loading=false,data=null,error=false;const lifecycle=new AbortController();
  const emit=()=>{if(!disposed)render({loading,data,error});};
  emit();
  return{
    async check(){
      if(disposed||loading)return false;
      loading=true;data=null;error=false;emit();
      try{
        const result=await client.integration(lifecycle.signal);
        if(disposed)return false;
        data=checked(result);if(!data)throw Error('Unverified diagnostics');
        return true;
      }catch{if(!disposed){data=null;error=true;}return false;}
      finally{if(!disposed){loading=false;emit();}}
    },
    dispose(){disposed=true;lifecycle.abort();data=null;},
  };
}
