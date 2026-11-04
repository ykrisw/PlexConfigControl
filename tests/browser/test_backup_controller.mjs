import test from 'node:test';
import assert from 'node:assert/strict';
import {createBackupController} from '../../plexconfigcontrol/static/backup-controller.mjs';
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const archive=(day='03',modified='1793664000000000123')=>({name:`TrueNASPlexConfig_2026.11.${day}_04.15.35.tar.gz`,size:'42',device:'1',inode:'9223372036854775931',modified_ns:modified});
function setup({rows=[archive()],allow=true,phase='IDLE',remove=async rows=>({deleted:rows.map(row=>row.name)})}={}){
  const source={rows,allow,phase},states=[],calls=[],scheduled=[];
  const client={archives:async()=>source.rows,capabilities:async()=>({archive_delete:source.allow}),
    operation:async()=>({operation:{phase:source.phase,snapshot_id:null},publication:{status:'NONE'}}),
    backupPlan:async()=>({archive_count:source.rows.length,action:source.rows.length===1?'ASK_OVERWRITE_OR_NEW':'CREATE_NEW',existing_archive:source.rows.length===1?source.rows[0]:null}),
    status:async()=>({state:'RUNNING',available:true}),
    deleteArchives:async rows=>{calls.push(rows);return remove(rows);}};
  const controller=createBackupController(client,state=>states.push(state),{schedule:fn=>{scheduled.push(fn);return scheduled.length;},cancel:()=>{}});
  return{controller,states,calls,source};
}

test('backup planning follows current counts 0, 1, 2, then back to 1',async()=>{
  const view=setup({rows:[]});await flush();
  assert.equal(view.states.at(-1).plan.action,'CREATE_NEW');
  view.source.rows=[archive()];await view.controller.refresh();assert.equal(view.states.at(-1).plan.action,'ASK_OVERWRITE_OR_NEW');
  view.source.rows=[archive(),archive('02')];await view.controller.refresh();assert.equal(view.states.at(-1).plan.action,'CREATE_NEW');
  view.source.rows=[archive('02')];await view.controller.refresh();assert.equal(view.states.at(-1).plan.action,'ASK_OVERWRITE_OR_NEW');
  assert.deepEqual(view.states.at(-1).selected,[]);view.controller.dispose();
});

test('read-only installation and active operations cannot delete selected archives',async()=>{
  const view=setup({allow:false});await flush();view.controller.select(archive().name,true);
  assert.equal(await view.controller.remove(view.controller.selection()),false);assert.equal(view.calls.length,0);
  view.source.allow=true;view.source.phase='VALIDATING';await view.controller.refresh();
  assert.equal(view.states.at(-1).canDelete,false);view.controller.dispose();
});

test('replacement invalidates a selection and its old confirmation',async()=>{
  const view=setup();await flush();view.controller.select(archive().name,true);const old=view.controller.selection();
  view.source.rows=[archive('03','1793664000000000999')];await view.controller.refresh();
  assert.deepEqual(view.states.at(-1).selected,[]);
  assert.equal(await view.controller.remove(old),false);assert.equal(view.calls.length,0);view.controller.dispose();
});

test('confirmed delete transmits exact nanoseconds and inode strings without rounding',async()=>{
  const view=setup();await flush();view.controller.select(archive().name,true);
  assert.equal(await view.controller.remove(view.controller.selection()),true);
  assert.equal(view.calls[0][0].modified_ns,'1793664000000000123');
  assert.equal(view.calls[0][0].inode,'9223372036854775931');view.controller.dispose();
});

test('ambiguous deletion is not retried and retains a warning after refresh',async()=>{
  const view=setup({remove:async()=>{throw Error('offline');}});await flush();view.controller.select(archive().name,true);
  await view.controller.remove(view.controller.selection());await flush();
  assert.equal(view.calls.length,1);assert.equal(view.states.at(-1).notice,'DELETE_UNCONFIRMED');view.controller.dispose();
});


test('external imports appear on refresh without auto-selection and vanish when removed outside the app',async()=>{
  const view=setup({rows:[]});await flush();
  assert.deepEqual(view.states.at(-1).entries,[]);
  const imported=archive('01');view.source.rows=[imported];await view.controller.refresh();
  assert.deepEqual(view.states.at(-1).entries,[imported]);
  assert.deepEqual(view.states.at(-1).selected,[]);
  assert.equal(view.states.at(-1).plan.archive_count,1);
  view.controller.select(imported.name,true);assert.deepEqual(view.states.at(-1).selected,[imported.name]);
  view.source.rows=[];await view.controller.refresh();
  assert.deepEqual(view.states.at(-1).entries,[]);assert.deepEqual(view.states.at(-1).selected,[]);
  assert.equal(view.calls.length,0);view.controller.dispose();
});

test('custom and default archive prefixes remain selectable alongside legacy names',async()=>{
  const rows=['Dupa','PlexConfig','TrueNASPlexConfig'].map(prefix=>({...archive(),name:`${prefix}_2026.11.03_04.15.35.tar.gz`}));
  const view=setup({rows});await flush();assert.equal(view.states.at(-1).available,true);
  for(const row of rows)view.controller.select(row.name,true);
  assert.equal(view.controller.selection().length,3);view.controller.dispose();
});
