import {createSubmission} from './submission-controller.mjs';
const fields=['name','size','device','inode','modified_ns'];
export const archiveIdentity=row=>JSON.stringify(fields.map(key=>row[key]));
const validArchive=row=>row&&typeof row.name==='string'&&/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}_\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2}\.tar\.gz$/.test(row.name)&&
  fields.slice(1).every(key=>typeof row[key]==='string'&&/^(0|[1-9][0-9]{0,19})$/.test(row[key]));

export function createBackupController(client,render,{schedule=setTimeout,cancel=clearTimeout,makeId}={}){
  let entries=[],selected=new Set(),available=false,loading=false,busy=false,disposed=false,timer,refreshing;
  let capabilities={},operation=null,plan=null,plex='UNKNOWN',error='',notice='';
  let manualCheck='';
  const lifecycle=new AbortController();
  const submission=createSubmission((request,signal)=>client.startBackup(request,signal),
    (id,signal)=>client.executionStatus(id,signal),()=>emit(),{kind:'BACKUP',...(makeId?{makeId}:{})});
  function executionFree(){return !['QUEUED','RUNNING','RECOVERY_REQUIRED'].includes(operation?.execution?.state)&&!submission.view().blocked;}
  function canCreate(){return available&&!loading&&!busy&&capabilities.backup_create===true&&plex==='RUNNING'&&plan&&executionFree()&&operation&&
    ['IDLE','SUCCESS','FAILED'].includes(operation.operation?.phase)&&!operation.operation.snapshot_id&&operation.publication?.status==='NONE';}
  function canDelete(){return executionFree()&&available&&capabilities.archive_delete===true&&operation&&
    ['IDLE','SUCCESS','FAILED'].includes(operation.operation?.phase)&&!operation.operation.snapshot_id&&operation.publication?.status==='NONE';}
  function emit(){if(!disposed)render({entries:entries.map(row=>({...row})),selected:[...selected],available,loading,busy,plex,error,notice,
    operation:operation?structuredClone(operation):null,submission:submission.view(),manualCheck,canCreate:Boolean(canCreate()),creationEnabled:capabilities.backup_create===true,overwriteEnabled:capabilities.backup_overwrite===true,canDelete:Boolean(canDelete()),deletionEnabled:capabilities.archive_delete===true,plan:plan?structuredClone(plan):null});}
  function refresh(){
    if(disposed||busy)return Promise.resolve(false);
    return refreshing??=refreshState().finally(()=>{refreshing=null;});
  }
  async function refreshState(){
    cancel(timer);loading=true;emit();
    const results=await Promise.allSettled([
      client.archives(lifecycle.signal),client.capabilities(lifecycle.signal),client.operation(lifecycle.signal),
      client.backupPlan(lifecycle.signal),client.status(lifecycle.signal),
    ]);
    if(disposed)return false;
    const [archives,caps,op,choice,status]=results;
    plex=status.status==='fulfilled'&&status.value?.available!==false&&['RUNNING','STOPPED'].includes(status.value?.state)?status.value.state:'UNKNOWN';
    capabilities=caps.status==='fulfilled'&&caps.value&&typeof caps.value==='object'?caps.value:{};
    operation=op.status==='fulfilled'?op.value:null;
    if(archives.status==='fulfilled'&&Array.isArray(archives.value)&&archives.value.every(validArchive)){
      const next=archives.value;
      selected=new Set([...selected].filter(name=>{
        const before=entries.find(row=>row.name===name),after=next.find(row=>row.name===name);
        return before&&after&&archiveIdentity(before)===archiveIdentity(after);
      }));
      entries=next;available=true;error='';
    }else{available=false;error=archives.reason?.message||'Archive list is unavailable';}
    plan=choice.status==='fulfilled'&&choice.value?.archive_count===entries.length&&
      (entries.length!==1||archiveIdentity(choice.value.existing_archive||{})===archiveIdentity(entries[0]))?choice.value:null;
    submission.observe(operation?.execution);
    loading=false;emit();timer=schedule(refresh,3000);
    return Boolean(operation&&operation.available!==false);
  }
  function selectedArchives(){return entries.filter(row=>selected.has(row.name)).map(row=>({...row}));}
  emit();void refresh();
  return{
    refresh,
    prepareBackup(){
      if(!canCreate())return null;
      return entries.length===1?{mode:'CHOICE',archive:{...entries[0]}}:{mode:'NEW'};
    },
    async startBackup(mode='NEW',confirmedArchive=null,prefix=''){
      if(!canCreate())return false;
      if(mode==='NEW'&&entries.length===1)return false;
      if(prefix&&!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(prefix))return false;
      if(mode!=='NEW'&&(!['ANOTHER','OVERWRITE'].includes(mode)||entries.length!==1||
          archiveIdentity(confirmedArchive||{})!==archiveIdentity(entries[0])||
          (mode==='OVERWRITE'&&capabilities.backup_overwrite!==true))){
        error='Archive selection changed. Refresh and confirm again.';emit();return false;
      }
      cancel(timer);manualCheck='';
      const result=await submission.submit({mode,confirmed:true,...(prefix?{prefix}:{}),...(mode==='NEW'?{}:{archive:{...confirmedArchive}})});
      if(!disposed)void refresh();return result;
    },
    async retrySubmission(){const result=await submission.retry();if(!disposed)void refresh();return result;},
    async checkSubmission(){
      const {canCheck,phase}=submission.view();
      if(disposed||!canCheck||manualCheck==='CHECKING')return false;
      manualCheck='CHECKING';emit();
      if(!['QUEUED','RUNNING'].includes(phase))await submission.check();
      if(refreshing)await refreshing;
      const refreshed=await refresh();
      if(disposed)return false;
      manualCheck=refreshed?'UPDATED':'UNAVAILABLE';emit();
      return refreshed;
    },
    select(name,checked){
      if(disposed||loading||busy||!available||!entries.some(row=>row.name===name))return;
      if(checked)selected.add(name);else selected.delete(name);notice='';emit();
    },
    selection:selectedArchives,
    async remove(confirmed){
      if(disposed||loading||busy||!canDelete())return false;
      const current=selectedArchives();
      if(!Array.isArray(confirmed)||!confirmed.length||confirmed.length>1000||
        JSON.stringify(confirmed.map(archiveIdentity).sort())!==JSON.stringify(current.map(archiveIdentity).sort())){
        error='Archive selection changed. Refresh and confirm again.';emit();return false;
      }
      busy=true;error='';notice='';cancel(timer);emit();
      try{
        const result=await client.deleteArchives(confirmed.map(row=>({...row})),lifecycle.signal);
        if(disposed)return false;
        if(!Array.isArray(result.deleted)||JSON.stringify([...result.deleted].sort())!==JSON.stringify(current.map(row=>row.name).sort()))throw Error('Deletion could not be confirmed');
        const removed=new Set(result.deleted);entries=entries.filter(row=>!removed.has(row.name));selected.clear();plan=null;
        notice='DELETED';return true;
      }catch(failure){if(!disposed){available=false;error=failure.message||'Deletion could not be confirmed';notice='DELETE_UNCONFIRMED';}return false;}
      finally{busy=false;emit();if(!disposed)void refresh();}
    },
    dispose(){disposed=true;submission.dispose();lifecycle.abort();cancel(timer);entries=[];selected.clear();},
  };
}
