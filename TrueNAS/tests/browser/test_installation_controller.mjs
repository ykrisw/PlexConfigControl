import test from 'node:test';
import assert from 'node:assert/strict';
import {createInstallationController,installationPreview} from '../../plexconfigcontrol/static/installation-controller.mjs';
const now=()=>new Date('2026-11-04T10:20:30Z');
const initial={phase:'UNVERIFIED',fields:[]};
const ready=inputs=>({phase:'READY',can_create:true,revision:'a'.repeat(32),storage:{type:'host_path',source:'/mnt/apps/Plex',dataset:'apps/plex',output:installationPreview(inputs,now()).folder,folder_name:inputs.folder_name||'Plex Backup',archive_prefix:inputs.archive_prefix||'PlexConfig',logs_folder:'Logs'}});
function setup(client){const states=[];return{controller:createInstallationController(client,state=>states.push(state),{initial,now}),states};}

test('path preview is local, uses fixed Logs/London timestamp and input edits invalidate a checked plan',async()=>{
  const checks=[],writes=[];const view=setup({check:async inputs=>{checks.push(inputs);return ready(inputs);},create:async request=>{writes.push(request);}});
  view.controller.edit('parent','/mnt/Pool_A/Backups');view.controller.edit('archive_prefix','Dupa');
  assert.equal(view.states.at(-1).preview.archive,'Dupa_2026.11.04_10.20.30.tar.gz');assert.equal(checks.length,0);
  assert.equal(await view.controller.check(),true);const confirmation=view.controller.confirmation();
  view.controller.edit('parent','/mnt/Pool_B');
  assert.equal(await view.controller.create(confirmation),false);assert.equal(writes.length,0);
  assert.equal(view.states.at(-1).preview.logs,'/mnt/Pool_B/Plex Backup/Logs');assert.equal(view.states.at(-1).canCreate,false);
  view.controller.dispose();
});

test('manual fallback preserves selected destination and retries only after an explicit check',async()=>{
  let calls=0;const view=setup({check:async inputs=>{calls++;return calls===1?{phase:'MANUAL_REQUIRED',error:{message:'Enter path'}}:ready(inputs);}});
  view.controller.edit('parent','/mnt/Backups');assert.equal(await view.controller.check(),false);
  assert.equal(view.states.at(-1).manual,true);assert.equal(view.states.at(-1).inputs.parent,'/mnt/Backups');assert.equal(calls,1);
  view.controller.edit('manual_source','/mnt/apps/Plex');assert.equal(await view.controller.check(),true);
  assert.equal(calls,2);view.controller.dispose();
});

test('stale or different server paths are rejected before creation can be confirmed',async()=>{
  const view=setup({check:async inputs=>{const reply=ready(inputs);reply.storage.output='/mnt/Other';return reply;}});
  view.controller.edit('parent','/mnt/Backups');assert.equal(await view.controller.check(),false);
  assert.equal(view.controller.confirmation(),null);assert.equal(view.states.at(-1).canCreate,false);view.controller.dispose();
});

test('creation is single-submit and an uncertain reply cannot be retried or rechecked',async()=>{
  let resolve,writes=0,checks=0;const view=setup({check:async inputs=>{checks++;return ready(inputs);},create:()=>{writes++;return new Promise(done=>{resolve=done;});}});
  view.controller.edit('parent','/mnt/Backups');await view.controller.check();const confirmation=view.controller.confirmation();
  const pending=view.controller.create(confirmation);assert.equal(await view.controller.create(confirmation),false);assert.equal(writes,1);
  resolve({phase:'READY'});assert.equal(await pending,false);assert.equal(view.states.at(-1).phase,'CREATE_UNCONFIRMED');
  await view.controller.create(confirmation);await view.controller.check();view.controller.edit('parent','/mnt/Elsewhere');
  assert.equal(writes,1);assert.equal(checks,1);assert.equal(view.states.at(-1).inputs.parent,'/mnt/Backups');view.controller.dispose();
});

test('confirmed creation needs matching destination and does not claim that a backup ran',async()=>{
  let selected;const view=setup({check:async inputs=>{selected=ready(inputs);return selected;},create:async()=>({...selected,phase:'COMPLETE',can_create:false,revision:null})});
  view.controller.edit('parent','/mnt/Backups');await view.controller.check();assert.equal(await view.controller.create(view.controller.confirmation()),true);
  assert.equal(view.states.at(-1).preview.created,true);assert.equal(view.states.at(-1).preview.example,true);assert.equal(view.states.at(-1).canCreate,false);view.controller.dispose();
});

test('disposing during a read or write cannot redraw the new screen',async()=>{
  let finish;const view=setup({check:()=>new Promise(done=>{finish=done;})});view.controller.edit('parent','/mnt/Backups');
  const pending=view.controller.check();const count=view.states.length;view.controller.dispose();finish(ready({parent:'/mnt/Backups'}));
  assert.equal(await pending,false);assert.equal(view.states.length,count);
});

test('invalid paths/prefixes cannot be checked and Unicode folder names remain supported',()=>{
  for(const inputs of [{parent:'../bad'},{parent:'//host/folder'},{parent:'/mnt/good',folder_name:'../bad'},{parent:'/mnt/good',archive_prefix:'a.tar.gz'}])assert.equal(installationPreview(inputs,now()),null);
  const preview=installationPreview({parent:'/mnt/Archiwum',folder_name:'Moje kopie Łódź'},new Date('2026-07-03T04:15:35Z'));
  assert.equal(preview.archive,'PlexConfig_2026.07.03_05.15.35.tar.gz');assert.equal(preview.folder,'/mnt/Archiwum/Moje kopie Łódź');
});


test('disposing during creation leaves the one submitted write alone and drops its late reply',async()=>{
  let finish,writes=0,selected;
  const view=setup({check:async inputs=>{selected=ready(inputs);return selected;},create:payload=>{writes++;assert.equal(payload.confirmed,true);return new Promise(done=>{finish=done;});}});
  view.controller.edit('parent','/mnt/Backups');await view.controller.check();
  const pending=view.controller.create(view.controller.confirmation());const count=view.states.length;view.controller.dispose();
  finish({...selected,phase:'COMPLETE'});assert.equal(await pending,false);assert.equal(writes,1);assert.equal(view.states.length,count);
});
