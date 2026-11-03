import test from 'node:test';
import assert from 'node:assert/strict';
import {createRecoveryController} from '../../plexconfigcontrol/static/recovery-controller.mjs';
const snapshot='test/config@pcc-backup-'+'a'.repeat(32);
const operation=(id=snapshot)=>({operation:{phase:'RECOVERY_REQUIRED',kind:'BACKUP',snapshot_id:id},publication:{pending:false}});
const result=(state='PRESENT',id=snapshot)=>({phase:'RECOVERY_REQUIRED',snapshot_id:id,snapshot_state:state,removal_supported:false,removal_available:false});
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
