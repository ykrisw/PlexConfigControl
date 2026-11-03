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
