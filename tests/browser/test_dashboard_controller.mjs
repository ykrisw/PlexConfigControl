import test from 'node:test';
import assert from 'node:assert/strict';
import {createDashboardController} from '../../plexconfigcontrol/static/dashboard-controller.mjs';

const flush = () => new Promise(resolve => setImmediate(resolve));
function setup(client) {
  const states = [], callbacks = [], reasons = [], cancellations = [];
  const controller = createDashboardController(client, value => states.push(value), {
    onSignedOut: value => reasons.push(value),
    schedule: callback => { callbacks.push(callback); return callbacks.length; },
    cancel: value => cancellations.push(value),
  });
  return {controller, states, callbacks, reasons, cancellations};
}

test('lost connection removes stale RUNNING status and polling remains sequential', async () => {
  let calls = 0;
  const view = setup({status: async () => { if (++calls === 1) return {state:'RUNNING',available:true}; throw Error('offline'); }});
  await flush(); assert.equal(view.states.at(-1).plex, 'RUNNING');
  assert.equal(calls,1); assert.equal(view.callbacks.length,1);
  await view.callbacks[0](); assert.equal(view.states.at(-1).plex,'UNKNOWN');
  assert.equal(calls,2); view.controller.dispose();
});

test('unavailable status never appears RUNNING and disposed reads never render', async () => {
  const view = setup({status: async () => ({state:'RUNNING',available:false})});
  await flush(); assert.equal(view.states.at(-1).plex,'UNKNOWN'); view.controller.dispose();
  let resolve;
  const pending = setup({status: () => new Promise(done => { resolve = done; })});
  pending.controller.dispose(); const count = pending.states.length;
  resolve({state:'RUNNING',available:true}); await flush();
  assert.equal(pending.states.length,count); assert.equal(pending.callbacks.length,0);
});

test('password mismatch makes no server call; successful change ends polling and signs out', async () => {
  const calls = [];
  const view = setup({status: async () => ({state:'STOPPED'}),
    changePassword: async (...args) => calls.push(args)});
  assert.equal(await view.controller.changePassword('old','one','two'),false);
  assert.equal(calls.length,0); assert.match(view.states.at(-1).error,/match/);
  assert.equal(await view.controller.changePassword('old','new','new'),true);
  assert.equal(calls.length,1); assert.deepEqual(view.reasons,['password_changed']);
  assert.equal(calls[0][3].aborted,true);
});

test('logout cannot duplicate requests or claim success on network failure', async () => {
  let reject, calls = 0;
  const view = setup({status: async () => ({state:'RUNNING'}),logout: () => {
    calls++; return new Promise((resolve, fail) => { reject = fail; });
  }});
  const pending = view.controller.logout();
  assert.equal(await view.controller.logout(),false); assert.equal(calls,1);
  reject(Error('Could not confirm logout')); assert.equal(await pending,false);
  assert.deepEqual(view.reasons,[]); assert.match(view.states.at(-1).error,/confirm/);
  view.controller.dispose();
});


test('confirmed password change with unavailable History still signs out with an explicit warning',async()=>{
  const reasons=[];const controller=createDashboardController({status:async()=>({state:'STOPPED',available:true}),
    changePassword:async()=>({changed:true,sign_in_required:true,history_recorded:false})},()=>{},
    {onSignedOut:reason=>reasons.push(reason),schedule:()=>1,cancel:()=>{}});
  assert.equal(await controller.changePassword('old','new','new'),true);
  assert.deepEqual(reasons,['password_changed_history_pending']);controller.dispose();
});
