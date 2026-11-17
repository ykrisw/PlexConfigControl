import test from 'node:test';
import assert from 'node:assert/strict';
import {createSubmission} from '../../plexconfigcontrol/static/submission-controller.mjs';
const id='a'.repeat(32),receipt={accepted:true,request_id:id,kind:'BACKUP',status_url:'/api/operation'};

test('concurrent clicks submit only once and disposal does not cancel the server operation',async()=>{
  let finish,calls=0;const renders=[];
  const flow=createSubmission(async()=>{calls++;return new Promise(resolve=>finish=resolve);},async()=>null,value=>renders.push(value),{kind:'BACKUP',makeId:()=>id});
  const pending=flow.submit({mode:'NEW',confirmed:true});
  assert.equal(await flow.submit({mode:'NEW',confirmed:true}),false);assert.equal(calls,1);
  const count=renders.length;flow.dispose();finish(receipt);await pending;
  assert.equal(renders.length,count);assert.equal(calls,1);
});

test('uncertain submission is never retried automatically and explicit retry preserves immutable payload and id',async()=>{
  const calls=[];let attempts=0;
  const flow=createSubmission(async request=>{calls.push(structuredClone(request));request.archive.name='mutated by transport';if(++attempts===1)throw Error('offline');return receipt;},
    async()=>({found:false,execution:null}),()=>{}, {kind:'BACKUP',makeId:()=>id});
  const payload={mode:'OVERWRITE',confirmed:true,archive:{name:'original'}};
  assert.equal(await flow.submit(payload),false);assert.equal(flow.view().phase,'UNCONFIRMED');assert.equal(calls.length,1);
  payload.archive.name='changed outside';await flow.check();assert.equal(flow.view().phase,'UNCONFIRMED');
  assert.equal(await flow.submit({mode:'NEW',confirmed:true}),false);assert.equal(calls.length,1);
  assert.equal(await flow.retry(),true);assert.deepEqual(calls[1],calls[0]);assert.equal(calls[1].archive.name,'original');
  assert.equal(flow.view().phase,'ACCEPTED');flow.dispose();
});

test('read-only status resolves an earlier request even when another job is the latest',async()=>{
  let sends=0;
  const flow=createSubmission(async()=>{sends++;throw Error('lost reply');},async request_id=>({found:true,execution:{request_id,kind:'BACKUP',state:'SUCCEEDED'}}),()=>{}, {kind:'BACKUP',makeId:()=>id});
  await flow.submit({mode:'NEW',confirmed:true});
  assert.equal(flow.observe({request_id:'b'.repeat(32),kind:'BACKUP',state:'RUNNING'}),false);
  await flow.check();assert.equal(flow.view().phase,'SUCCEEDED');assert.equal(flow.view().blocked,false);assert.equal(sends,1);flow.dispose();
});

test('late status cannot downgrade a confirmed completion or overwrite a newer request',async()=>{
  let resolveStatus;
  const flow=createSubmission(async()=>receipt,()=>new Promise(resolve=>resolveStatus=resolve),()=>{}, {kind:'BACKUP',makeId:()=>id});
  await flow.submit({mode:'NEW',confirmed:true});const pending=flow.check();
  flow.observe({request_id:id,kind:'BACKUP',state:'SUCCEEDED'});
  resolveStatus({found:false,execution:null});await pending;
  assert.equal(flow.view().phase,'SUCCEEDED');
  flow.observe({request_id:id,kind:'BACKUP',state:'RUNNING'});assert.equal(flow.view().phase,'SUCCEEDED');flow.dispose();
});

test('a late check of an earlier request does not keep the next request stuck checking',async()=>{
  let next=0,resolveOld;
  const flow=createSubmission(async request=>({...receipt,request_id:request.request_id}),()=>new Promise(resolve=>resolveOld=resolve),()=>{},
    {kind:'BACKUP',makeId:()=>++next===1?id:'b'.repeat(32)});
  await flow.submit({mode:'NEW',confirmed:true});const checking=flow.check();
  flow.observe({request_id:id,kind:'BACKUP',state:'SUCCEEDED'});
  await flow.submit({mode:'NEW',confirmed:true});assert.equal(flow.view().request_id,'b'.repeat(32));
  resolveOld({found:true,execution:{request_id:id,kind:'BACKUP',state:'RUNNING'}});await checking;
  assert.equal(flow.view().checking,false);assert.equal(flow.view().phase,'ACCEPTED');assert.equal(flow.view().canCheck,true);flow.dispose();
});
