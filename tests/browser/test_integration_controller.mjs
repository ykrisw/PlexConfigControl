import test from 'node:test';
import assert from 'node:assert/strict';
import {createIntegrationController} from '../../plexconfigcontrol/static/integration-controller.mjs';
import {mountIntegrationView} from '../../plexconfigcontrol/static/integration-view.mjs';
const result=()=>({schema:1,checked_at:'2026-11-03T12:00:00Z',backup_available:false,restore_available:false,
  execution_reason:'HOST_EXECUTION_NOT_CONNECTED',plex:{configured:false,state:'NOT_CONFIGURED',app_state:'UNKNOWN'},
  archives:{configured:true,state:'LIST_VERIFIED',count:0},snapshot:{configured:false,state:'NOT_CONFIGURED'},
  operation:{state:'IDLE',phase:'IDLE'}});

test('checks require an explicit click and cannot run duplicate requests',async()=>{
  let calls=0,resolve;const states=[];
  const controller=createIntegrationController({integration:()=>{calls++;return new Promise(done=>resolve=done);}},state=>states.push(state));
  assert.equal(calls,0);assert.equal(states.at(-1).data,null);
  const request=controller.check();assert.equal(await controller.check(),false);assert.equal(calls,1);
  resolve(result());assert.equal(await request,true);assert.equal(states.at(-1).data.archives.count,0);
  assert.equal(states.at(-1).data.backup_available,false);controller.dispose();
});

test('failed reads clear previous confirmations without exposing transport errors',async()=>{
  let calls=0;const states=[];
  const controller=createIntegrationController({integration:async()=>{if(++calls===1)return result();throw Error('private secret');}},state=>states.push(state));
  await controller.check();assert.ok(states.at(-1).data);await controller.check();
  assert.equal(states.at(-1).data,null);assert.equal(states.at(-1).error,true);
  assert.equal(JSON.stringify(states).includes('secret'),false);controller.dispose();
});

test('malformed diagnostics or unexpected execution support cannot be trusted',async()=>{
  for(const mutate of [r=>r.backup_available=true,r=>r.restore_available=true,r=>r.archives.count=-1,
    r=>r.plex.state='READY',r=>r.plex.app_state='RUNNING',r=>r.snapshot.state='PRESENT',r=>r.checked_at='bad']){
    const value=result();mutate(value);const states=[];
    const controller=createIntegrationController({integration:async()=>value},state=>states.push(state));
    assert.equal(await controller.check(),false);assert.equal(states.at(-1).data,null);controller.dispose();
  }
});

test('disposal aborts reads and ignores results after logout',async()=>{
  let resolve,signal;const states=[];
  const controller=createIntegrationController({integration:input=>{signal=input;return new Promise(done=>resolve=done);}},state=>states.push(state));
  const request=controller.check();controller.dispose();const count=states.length;
  assert.equal(signal.aborted,true);resolve(result());assert.equal(await request,false);
  assert.equal(states.length,count);assert.equal(await controller.check(),false);
});

test('only whitelisted diagnostic fields reach the rendered state',async()=>{
  const value=result();value.private_key='secret';value.plex.url='secret';const states=[];
  const controller=createIntegrationController({integration:async()=>value},state=>states.push(state));
  assert.equal(await controller.check(),true);assert.equal(JSON.stringify(states).includes('secret'),false);controller.dispose();
});

test('settings show the check date and whole seconds in UTC in both languages',async()=>{
  const elements=new Map();
  let click;
  const root={classList:{add(){}},ownerDocument:{createElement:()=>({})},replaceChildren(){},
    querySelector(selector){
      if(!elements.has(selector)) elements.set(selector,{replaceChildren(){},append(){},
        addEventListener(_event,handler){click=handler;}});
      return elements.get(selector);
    }};
  const view=mountIntegrationView(root,{integration:async()=>({...result(),checked_at:'2026-11-10T09:51:53.814+01:00'})},{language:'pl'});
  const checked=elements.get('[data-integration-checked]');
  assert.equal(checked.textContent,'');
  click();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(checked.textContent,'UTC: 2026-11-10 Czas: 08:51:53');
  view.setLanguage('en');
  assert.equal(checked.textContent,'UTC: 2026-11-10 Time: 08:51:53');
  view.dispose();
});
