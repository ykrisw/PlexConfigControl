import test from 'node:test';
import assert from 'node:assert/strict';
import {createRecoveryController} from '../../plexconfigcontrol/static/recovery-controller.mjs';
const snapshot='test/config@pcc-backup-'+'a'.repeat(32);
const none=()=>({pending:false,status:'NONE',archive:null,temporary_file:null});
const operation=(id=snapshot,record=none(),phase='RECOVERY_REQUIRED')=>({operation:{phase,kind:'BACKUP',snapshot_id:id},publication:record});
const result=(state='PRESENT',id=snapshot,record=none(),phase='RECOVERY_REQUIRED')=>({phase,kind:'BACKUP',snapshot_id:id,snapshot_state:state,removal_supported:false,removal_available:false,publication:record,publication_resolution_supported:false});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function setup(client){
  const states=[],timers=[];
  const controller=createRecoveryController(client,state=>states.push(state),{schedule:fn=>{timers.push(fn);return timers.length;},cancel:()=>{}});
  return{controller,states,timers};
}

test('ordinary panels do not show recovery or query snapshots',async()=>{
  let calls=0;const view=setup({recovery:async()=>{calls++;return result();}});
  view.controller.observe({operation:{phase:'IDLE'}});await flush();
  assert.equal(calls,0);assert.equal(view.states.at(-1).visible,false);view.controller.dispose();
});

test('verified recovery is shown without adding a snapshot removal capability',async()=>{
  let calls=0;const view=setup({recovery:async()=>{calls++;return result();}});
  view.controller.observe(operation());await flush();
  assert.equal(view.states.at(-1).data.snapshot_state,'PRESENT');
  assert.equal(view.states.at(-1).data.removal_supported,false);
  view.controller.observe(operation());await flush();assert.equal(calls,1);
  view.controller.dispose();
});

test('connection failure clears a previously confirmed snapshot state',async()=>{
  let calls=0;const view=setup({recovery:async()=>{if(++calls===1)return result();throw Error('private transport secret');}});
  view.controller.observe(operation());await flush();await view.controller.refresh();
  assert.equal(view.states.at(-1).data,null);assert.equal(view.states.at(-1).error,true);
  assert.equal(JSON.stringify(view.states).includes('secret'),false);view.controller.dispose();
});

test('an old reply cannot overwrite a new snapshot or redraw after logout',async()=>{
  const releases=[];const view=setup({recovery:()=>new Promise(resolve=>releases.push(resolve))});
  view.controller.observe(operation());view.controller.observe(operation(snapshot+'b'));
  releases[1](result('ABSENT',snapshot+'b'));await flush();
  releases[0](result());await flush();
  assert.equal(view.states.at(-1).data.snapshot_state,'ABSENT');
  const pending=view.controller.refresh();const count=view.states.length;view.controller.dispose();
  releases[2](result('PRESENT',snapshot+'b'));await pending;
  assert.equal(view.states.length,count);
});

test('wrong identity, invalid state or unexpected removal support is never trusted',async()=>{
  for(const reply of [result('ABSENT','wrong'),result('deleted'),{...result(),removal_supported:true}]){
    const view=setup({recovery:async()=>reply});view.controller.observe(operation());await flush();
    assert.equal(view.states.at(-1).data,null);assert.equal(view.states.at(-1).error,true);view.controller.dispose();
  }
});

test('no recorded snapshot still shows unresolved publication without inventing a snapshot',async()=>{
  const view=setup({recovery:async()=>result('NONE',null)});
  view.controller.observe(operation(null));await flush();assert.equal(view.states.at(-1).visible,true);
  assert.equal(view.states.at(-1).data.snapshot_state,'NONE');
  view.controller.observe({operation:{phase:'FAILED',snapshot_id:null}});
  assert.equal(view.states.at(-1).visible,false);assert.equal(view.states.at(-1).data,null);view.controller.dispose();
});


test('missing operation state invalidates an in-flight reply and a later valid poll recovers',async()=>{
  const releases=[];const view=setup({recovery:()=>new Promise(resolve=>releases.push(resolve))});
  view.controller.observe(operation());view.controller.observe(null);
  releases[0](result());await flush();
  assert.equal(view.states.at(-1).data,null);assert.equal(view.states.at(-1).error,true);
  view.controller.observe(operation());releases[1](result());await flush();
  assert.equal(view.states.at(-1).data.snapshot_state,'PRESENT');view.controller.dispose();
});

const archive='TrueNASPlexConfig_2026.11.03_12.00.00.tar.gz';
const stage='.pcc-'+'a'.repeat(32)+'.tmp';
const pending=()=>({pending:true,status:'VERIFICATION_REQUIRED',archive,temporary_file:stage});

test('publication details remain visible for a FAILED checkpoint and never grant resolution',async()=>{
  const record=pending(),view=setup({recovery:async()=>result('NONE',null,record,'FAILED')});
  view.controller.observe(operation(null,record,'FAILED'));await flush();
  assert.equal(view.states.at(-1).visible,true);
  assert.equal(view.states.at(-1).data.publication.archive,archive);
  assert.equal(view.states.at(-1).data.publication_resolution_supported,false);
  view.controller.dispose();
});

test('a changed publication record invalidates an in-flight response without a snapshot',async()=>{
  const replies=[],old=pending(),next={...pending(),temporary_file:'.pcc-'+'b'.repeat(32)+'.tmp'};
  const view=setup({recovery:()=>new Promise(resolve=>replies.push(resolve))});
  view.controller.observe(operation(null,old));view.controller.observe(operation(null,next));
  replies[1](result('NONE',null,next));await flush();replies[0](result('NONE',null,old));await flush();
  assert.equal(view.states.at(-1).data.publication.temporary_file,next.temporary_file);
  view.controller.dispose();
});

test('foreign or malformed publication replies and mutation capabilities are rejected',async()=>{
  for(const reply of [result('NONE',null,{...pending(),archive:'secret/path'}),
                      result('NONE',null,none()),
                      {...result('NONE',null,pending()),publication_resolution_supported:true},
                      {...result('NONE',null,pending()),kind:'RESTORE'}]){
    const view=setup({recovery:async()=>reply});view.controller.observe(operation(null,pending()));await flush();
    assert.equal(view.states.at(-1).data,null);assert.equal(view.states.at(-1).error,true);view.controller.dispose();
  }
});

test('unreadable marker is shown without exposing its contents and network failure clears details',async()=>{
  const record={pending:true,status:'RECORD_UNREADABLE',archive:null,temporary_file:null};
  let calls=0;const view=setup({recovery:async()=>{if(++calls===1)return result('NONE',null,record);throw Error('private secret');}});
  view.controller.observe(operation(null,record));await flush();
  assert.equal(view.states.at(-1).data.publication.status,'RECORD_UNREADABLE');
  await view.controller.refresh();assert.equal(view.states.at(-1).data,null);assert.equal(view.states.at(-1).error,true);
  view.controller.dispose();
});

test('ordinary active publication is not mislabeled interrupted and missing metadata cannot confirm recovery',async()=>{
  let calls=0;const view=setup({recovery:async()=>{calls++;return result();}});
  view.controller.observe(operation(null,pending(),'RUNNING'));await flush();
  assert.equal(view.states.at(-1).visible,false);assert.equal(calls,0);
  view.controller.observe({...operation(null),publication:undefined});await flush();
  assert.equal(view.states.at(-1).visible,true);assert.equal(view.states.at(-1).error,true);assert.equal(calls,0);
  view.controller.dispose();
});

test('a stale historical outcome cannot replace a newer publication warning',async()=>{
  const record=pending(),before={code:'BACKUP_PUBLICATION_UNCERTAIN',archive},after={code:'BACKUP_PUBLISHED_REVIEW',archive};
  const releases=[];const view=setup({recovery:()=>new Promise(resolve=>releases.push(resolve))});
  view.controller.observe({...operation(null,record),operation:{...operation(null).operation,outcome:before}});
  view.controller.observe({...operation(null,record),operation:{...operation(null).operation,outcome:after}});
  releases[1]({...result('NONE',null,record),outcome:after});await flush();
  releases[0]({...result('NONE',null,record),outcome:before});await flush();
  assert.equal(view.states.at(-1).data.outcome.code,after.code);view.controller.dispose();
});
