import test from 'node:test';
import assert from 'node:assert/strict';
import {RestoreController} from '../../plexconfigcontrol/static/restore-panel.mjs';

test('no archive is auto-selected and repeated clicks do not duplicate validation', async () => {
  let validations=0,release;
  const gate=new Promise(resolve => release=resolve);
  const client={validateArchive:async name => {assert.equal(name,'chosen'); validations++; await gate;},
    restoreView:async () => ({operation:{operation:{phase:'VALIDATING'}},readiness:null})};
  const controller=new RestoreController(client,()=>{});
  await controller.validate(); assert.equal(validations,0);
  controller.select('chosen'); const first=controller.validate();
  await controller.validate(); controller.select('other');
  assert.equal(validations,1); assert.equal(controller.state.selected,'chosen');
  release(); await first;
  assert.equal(controller.state.busy,false);
  assert.equal(controller.state.snapshot.readiness,null);
});

test('lost connection clears previously ready view and failed POST is never retried', async () => {
  let posts=0;
  const client={restoreView:async () => {throw new Error('Connection unavailable');},
    validateArchive:async () => {posts++; throw new Error('Request outcome unknown');}};
  const controller=new RestoreController(client,()=>{});
  controller.state.snapshot={readiness:{ready:true}};
  await controller.refresh();
  assert.equal(controller.state.snapshot,null);
  assert.equal(controller.state.error,'Connection unavailable');
  controller.select('chosen'); await controller.validate();
  assert.equal(posts,1); assert.equal(controller.state.error,'Request outcome unknown');
});

test('leaving panel does not cancel server operation and late responses do not render', async () => {
  let release,renders=0,cancels=0;
  const client={restoreView:()=>new Promise(resolve => release=resolve),cancelRestore:async () => cancels++};
  const controller=new RestoreController(client,()=>renders++);
  const pending=controller.refresh(); controller.dispose();
  release({readiness:{ready:true}}); await pending;
  assert.equal(renders,0); assert.equal(cancels,0);
});

test('older IDLE replies cannot overwrite a newer validation response',async()=>{
  const replies=[];
  const client={restoreView:()=>new Promise(resolve=>replies.push(resolve))};
  const controller=new RestoreController(client,()=>{});
  const older=controller.refresh(),newer=controller.refresh();
  const active={operation:{operation:{phase:'VALIDATING',kind:'RESTORE'}},readiness:null};
  replies[1](active);await newer;
  replies[0]({operation:{operation:{phase:'IDLE'}}});await older;
  assert.equal(controller.state.snapshot,active);controller.dispose();
});

test('late failed refresh does not clear a newer verified waiting state',async()=>{
  let fail,finish,calls=0;
  const client={restoreView:()=>++calls===1?new Promise((resolve,reject)=>{fail=reject;}):new Promise(resolve=>{finish=resolve;})};
  const controller=new RestoreController(client,()=>{});
  const older=controller.refresh(),newer=controller.refresh();
  const waiting={operation:{operation:{phase:'WAITING_FOR_PLEX_STOP',kind:'RESTORE'}}};
  finish(waiting);await newer;fail(Error('old connection failure'));await older;
  assert.equal(controller.state.snapshot,waiting);assert.equal(controller.state.error,null);controller.dispose();
});

test('waiting restore rejects selection changes and duplicate validation; removed selection is cleared',async()=>{
  let posts=0;
  const client={validateArchive:async()=>posts++};
  const controller=new RestoreController(client,()=>{});
  controller.select('chosen');controller.state.snapshot={operation:{operation:{phase:'WAITING_FOR_PLEX_STOP',kind:'RESTORE'}}};
  controller.select('other');await controller.validate();
  assert.equal(controller.state.selected,'chosen');assert.equal(posts,0);
  controller.reconcileSelection(['other']);assert.equal(controller.state.selected,null);
  controller.dispose();controller.select('chosen');await controller.validate();assert.equal(posts,0);
});


test('pending publication prevents selection validation and cancellation requests',async()=>{
  let posts=0;
  const controller=new RestoreController({validateArchive:async()=>posts++,cancelRestore:async()=>posts++},()=>{});
  controller.state.selected='chosen';
  for(const phase of ['FAILED','READY']){
    controller.state.snapshot={operation:{operation:{phase,kind:'RESTORE'},publication:{pending:true}}};
    controller.select('other');await controller.validate();await controller.cancel();
    assert.equal(controller.state.selected,'chosen');assert.equal(posts,0);
  }
  controller.dispose();
});
