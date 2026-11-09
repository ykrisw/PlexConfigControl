import test from 'node:test';
import assert from 'node:assert/strict';
import {createBackupController} from '../../plexconfigcontrol/static/backup-controller.mjs';
import {RestoreController} from '../../plexconfigcontrol/static/restore-panel.mjs';
import {mountStageProgress} from '../../plexconfigcontrol/static/operation-workspace.mjs';
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const id='a'.repeat(32),name='TrueNASPlexConfig_2026.11.03_04.15.35.tar.gz';
const row=()=>({name,size:'42',device:'1',inode:'9223372036854775931',modified_ns:'1793664000000000123'});

test('only measured progress from the current operation gets a percentage',()=>{
  const bar={removeAttribute:()=>delete bar.value},label={};
  const meter={querySelector:selector=>selector==='progress'?bar:label};
  const show=mountStageProgress(meter,'RESTORE','pl');
  show(true,{operation:'BACKUP',active:true,stage_percent:70});
  assert.equal(meter.hidden,false);assert.equal(bar.value,undefined);assert.equal(label.hidden,true);
  show(true,{operation:'RESTORE',active:true,stage_percent:37.5});
  assert.equal(bar.value,37.5);assert.equal(label.textContent,'37,5%');
  show(false,{operation:'RESTORE',active:false,stage_percent:100});
  assert.equal(meter.hidden,true);assert.equal(bar.value,undefined);assert.equal(label.textContent,'');
});
function backup(rows=[]){
  const source={rows,enabled:true,plex:'RUNNING'},states=[],posts=[];
  const client={archives:async()=>source.rows,capabilities:async()=>({backup_create:source.enabled,backup_overwrite:true}),
    operation:async()=>({operation:{phase:'IDLE',snapshot_id:null},publication:{status:'NONE'}}),
    status:async()=>({state:source.plex,available:true}),
    backupPlan:async()=>({archive_count:source.rows.length,action:source.rows.length===1?'ASK_OVERWRITE_OR_NEW':'CREATE_NEW',existing_archive:source.rows.length===1?source.rows[0]:null}),
    startBackup:async request=>{posts.push(request);return{accepted:true,request_id:request.request_id,kind:'BACKUP',status_url:'/api/operation'};},executionStatus:async()=>({found:false,execution:null})};
  const controller=createBackupController(client,value=>states.push(value),{schedule:()=>0,cancel:()=>{},makeId:()=>id});
  return {source,states,posts,controller,client};
}

test('zero or multiple archives create a new copy; exactly one requires its current confirmed identity',async()=>{
  for(const rows of [[],[row(),{...row(),name:name.replace('_04.','_05.')}]] ){
    const view=backup(rows);await flush();assert.equal(view.controller.prepareBackup().mode,'NEW');
    await view.controller.startBackup();assert.equal(view.posts.length,1);assert.equal(view.posts[0].mode,'NEW');view.controller.dispose();
  }
  const view=backup([row()]);await flush();const shown=view.controller.prepareBackup();assert.equal(shown.mode,'CHOICE');
  assert.equal(await view.controller.startBackup(),false);assert.equal(view.posts.length,0);
  await view.controller.startBackup('OVERWRITE',shown.archive);assert.equal(view.posts[0].archive.inode,row().inode);assert.equal(view.posts[0].archive.modified_ns,row().modified_ns);
  assert.equal(view.posts[0].request_id,id);view.controller.dispose();
});

test('changed choice, stopped Plex or missing backend capability blocks Backup before POST',async()=>{
  const view=backup([row()]);await flush();const shown=view.controller.prepareBackup();
  view.source.rows=[{...row(),modified_ns:'1793664000000000999'}];await view.controller.refresh();
  assert.equal(await view.controller.startBackup('ANOTHER',shown.archive),false);assert.equal(view.posts.length,0);
  view.source.plex='STOPPED';await view.controller.refresh();assert.equal(view.controller.prepareBackup(),null);
  view.source.plex='RUNNING';view.source.enabled=false;await view.controller.refresh();assert.equal(view.controller.prepareBackup(),null);assert.equal(view.posts.length,0);view.controller.dispose();
});

function restore(){
  const snapshot={operation:{operation:{kind:'RESTORE',phase:'WAITING_FOR_PLEX_STOP',snapshot_id:null,outcome:null,
      archive_identity:'b'.repeat(64),validation_details:{status:'VALID',archive:name,sha256:'b'.repeat(64)}},publication:{pending:false}},
    readiness:{ready:true,archive:name,plex:{state:'STOPPED',available:true}},capabilities:{restore_execute:true}};
  const posts=[],states=[];
  const client={restoreView:async()=>snapshot,executeRestore:async request=>{posts.push(request);return{accepted:true,request_id:request.request_id,kind:'RESTORE',status_url:'/api/operation'};},executionStatus:async()=>({found:false,execution:null})};
  const controller=new RestoreController(client,value=>states.push(value),{makeId:()=>id});controller.select(name);
  return{snapshot,posts,states,controller};
}

test('Restore requires literal confirmation and unchanged validated digest; duplicate execution is blocked',async()=>{
  const view=restore();await view.controller.refresh();const shown=view.controller.prepareExecution();assert.ok(shown);
  assert.equal(await view.controller.execute(shown,'yes'),false);assert.equal(view.posts.length,0);
  assert.equal(await view.controller.execute(shown,'RESTORE'),true);assert.equal(view.posts.length,1);
  assert.equal(await view.controller.execute(shown,'RESTORE'),false);assert.equal(view.posts.length,1);
  assert.equal(view.posts[0].sha256,'b'.repeat(64));view.controller.dispose();
});

test('Restore readiness, capability and changed digest invalidate the open confirmation',async()=>{
  const view=restore();await view.controller.refresh();const shown=view.controller.prepareExecution();
  view.snapshot.readiness.plex.state='RUNNING';assert.equal(view.controller.prepareExecution(),null);
  view.snapshot.readiness.plex.state='STOPPED';view.snapshot.capabilities.restore_execute=false;assert.equal(view.controller.prepareExecution(),null);
  view.snapshot.capabilities.restore_execute=true;view.snapshot.operation.operation.archive_identity='c'.repeat(64);view.snapshot.operation.operation.validation_details.sha256='c'.repeat(64);
  assert.equal(await view.controller.execute(shown,'RESTORE'),false);assert.equal(view.posts.length,0);view.controller.dispose();
});
