import test from 'node:test';
import assert from 'node:assert/strict';
import {createHistoryController} from '../../plexconfigcontrol/static/history-controller.mjs';

const flush = () => new Promise(resolve => setImmediate(resolve));
const events = [
  {id:3,kind:'RESTORE',status:'FAILED'},
  {id:2,kind:'BACKUP',status:'SUCCESS'},
  {id:1,kind:'LOGIN',status:'SUCCESS'},
];
function setup(client) {
  const states=[],timers=[];
  const controller=createHistoryController(client,value=>states.push(value),{
    schedule:callback=>{timers.push(callback);return timers.length;},cancel:()=>{},
  });
  return {controller,states,timers};
}

test('real counts, filters and multi-selection never auto-select history events',async()=>{
  const view=setup({history:async()=>events}); await flush();
  assert.deepEqual(view.states.at(-1).counts,{all:3,backup:1,restore:1,success:2,failed:1});
  assert.deepEqual(view.states.at(-1).selected,[]);
  view.controller.select(3,true);view.controller.select(2,true);
  assert.deepEqual(view.states.at(-1).selected,[3,2]);
  view.controller.setFilter('BACKUP');
  assert.deepEqual(view.states.at(-1).entries,[events[1]]);
  assert.deepEqual(view.states.at(-1).selected,[]);
  view.controller.select(3,true);assert.deepEqual(view.states.at(-1).selected,[]);
  view.controller.dispose();
});

test('refresh preserves surviving selections and rejects an outdated confirmation',async()=>{
  let rows=events,calls=0;
  const view=setup({history:async()=>rows,clearHistory:async()=>{calls++;return {cleared:[3]};}});
  await flush();view.controller.select(3,true);
  rows=events.filter(x=>x.id!==3);await view.controller.refresh();
  assert.deepEqual(view.states.at(-1).selected,[]);
  assert.equal(await view.controller.clear([3]),null);assert.equal(calls,0);
  view.controller.dispose();
});

test('confirmed clear deletes exactly the selected records and prevents duplicate requests',async()=>{
  let finish,calls=0;
  const view=setup({history:async()=>events,clearHistory:ids=>{
    calls++;return new Promise(resolve=>{finish=()=>resolve({cleared:ids});});
  }});
  await flush();view.controller.select(2,true);
  const pending=view.controller.clear([2]);
  assert.equal(await view.controller.clear([2]),null);assert.equal(calls,1);
  finish();await pending;
  assert.deepEqual(view.states.at(-1).entries.map(x=>x.id),[3,1]);
  assert.equal(view.states.at(-1).notice,'CLEARED');view.controller.dispose();
});

test('failed deletion disables stale actions without automatically retrying the POST',async()=>{
  let calls=0;
  const view=setup({history:async()=>events,clearHistory:async()=>{calls++;throw Error('connection lost');}});
  await flush();view.controller.select(2,true);await view.controller.clear([2]);
  assert.equal(view.states.at(-1).available,false);
  assert.equal(await view.controller.clear([2]),null);assert.equal(calls,1);
  await view.controller.refresh();
  assert.equal(view.states.at(-1).available,true);
  assert.equal(view.states.at(-1).notice,'CLEAR_UNCONFIRMED');
  assert.equal(calls,1);
  view.controller.dispose();
});

test('download uses selected identities and disposed requests cannot deliver a file',async()=>{
  let complete,requested;
  const view=setup({history:async()=>events,downloadHistory:ids=>{
    requested=ids;return new Promise(resolve=>{complete=resolve;});
  }});
  await flush();view.controller.select(2,true);view.controller.select(3,true);
  const pending=view.controller.download([2,3]);assert.deepEqual(requested,[2,3]);
  view.controller.dispose();const count=view.states.length;
  complete({filename:'logs.zip',blob:{}});
  assert.equal(await pending,null);assert.equal(view.states.length,count);
});


test('archive detection is a selectable backup event without being counted as a success',async()=>{
  const detected={id:4,kind:'ARCHIVE_DETECTED',status:'INFO',archive:'external.tar.gz'};
  const view=setup({history:async()=>[detected,...events],downloadHistory:async ids=>({ids})});await flush();
  assert.equal(view.states.at(-1).counts.all,4);
  assert.equal(view.states.at(-1).counts.success,2);
  assert.equal(view.states.at(-1).counts.backup,2);
  view.controller.setFilter('BACKUP');
  assert.deepEqual(view.states.at(-1).entries,[detected,events[1]]);
  view.controller.select(4,true);assert.deepEqual((await view.controller.download([4])).ids,[4]);
  view.controller.dispose();
});

test('adding and verifying an archive updates backup events and both file counters without a restore',async()=>{
  const detected = {id:4,kind:'ARCHIVE_DETECTED',status:'INFO',archive:'external.tar.gz'};
  const validation = {id:5,kind:'ARCHIVE_VALIDATION',status:'SUCCESS',archive:detected.archive};
  let archives = [], history = [];
  const view = setup({
    history:async()=>history,
    archives:async(_signal, options)=>{
      assert.deepEqual(options,{verification:true});
      if (archives === null) throw Error('Archive folder unavailable');
      return archives;
    },
  });
  await flush();
  view.controller.setFilter('BACKUP');
  assert.equal(view.states.at(-1).archiveCount,0);
  assert.equal(view.states.at(-1).counts.backup,0);
  archives = [{name:detected.archive,verified:false}];
  history = [detected];
  await view.controller.refresh();
  assert.equal(view.states.at(-1).archiveCount,1);
  assert.equal(view.states.at(-1).verifiedCount,0);
  assert.equal(view.states.at(-1).counts.backup,1);
  assert.deepEqual(view.states.at(-1).entries,[detected]);
  archives = [{name:detected.archive,verified:true}];
  history = [validation,detected];
  await view.controller.refresh();
  assert.equal(view.states.at(-1).archiveCount,1);
  assert.equal(view.states.at(-1).verifiedCount,1);
  assert.equal(view.states.at(-1).counts.backup,2);
  assert.deepEqual(view.states.at(-1).entries,[validation,detected]);
  view.controller.setFilter('RESTORE');
  assert.equal(view.states.at(-1).counts.restore,0);
  assert.deepEqual(view.states.at(-1).entries,[]);
  archives = [];
  await view.controller.refresh();
  assert.equal(view.states.at(-1).archiveCount,0);
  assert.equal(view.states.at(-1).verifiedCount,0);
  archives = null;
  await view.controller.refresh();
  assert.equal(view.states.at(-1).archiveCount,null);
  assert.equal(view.states.at(-1).verifiedCount,null);
  assert.equal(view.states.at(-1).available,true);
  view.controller.dispose();
});


test('history exposes queued permanent logs without claiming a read-only destination was written',async()=>{
  const view=setup({history:async()=>events,operation:async()=>({archive_discovery:{pending_logs:3,permanent_logs_enabled:false}})});
  await flush();assert.deepEqual(view.states.at(-1).archiveLogs,{pending:3,enabled:false});
  assert.equal(view.states.at(-1).available,true);view.controller.dispose();
});
