// Display names come from the operation being shown, never its comparison archive.
export function backupSubmission(value){
  const submission=value.submission||{}, snapshot=value.operation;
  const matching=snapshot?.execution?.kind==='BACKUP'&&
    snapshot.execution.request_id===submission.request_id;
  const archive=matching?snapshot.operation?.outcome?.archive:null;
  return {...submission,archive:typeof archive==='string'?archive:null};
}
export function restoreProgressName(state){
  if(state.busy&&state.selected)return state.selected;
  const snapshot=state.snapshot?.operation;
  if(snapshot?.operation?.kind!=='RESTORE')return null;
  return snapshot.progress?.archive||snapshot.operation.outcome?.archive||
    snapshot.operation.validation_details?.archive||state.selected||null;
}
export function archiveProgress(name,text){
  return text&&typeof name==='string'&&name?name+' — '+text:text;
}
