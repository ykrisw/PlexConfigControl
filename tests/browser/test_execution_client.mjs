import test from 'node:test';
import assert from 'node:assert/strict';
import {PanelClient} from '../../plexconfigcontrol/static/panel-client.mjs';
const request_id='a'.repeat(32);

test('Backup and Restore submit once with CSRF and return acceptance rather than success',async()=>{
  for(const [method,path,kind] of [['startBackup','/api/backup/start','BACKUP'],['executeRestore','/api/restore/execute','RESTORE']]){
    const calls=[];
    const client=new PanelClient({fetcher:async(url,options)=>{
      calls.push({url,options});return {ok:true,json:async()=>({accepted:true,request_id,kind,status_url:'/api/operation'})};
    }});
    client.csrf='csrf';
    const data=kind==='BACKUP'?{request_id,mode:'NEW',confirmed:true}:{request_id,archive:'example',sha256:'b'.repeat(64),confirmation:'RESTORE'};
    const result=await client[method](data);
    assert.deepEqual(result,{accepted:true,request_id,kind,status_url:'/api/operation'});
    assert.equal(calls.length,1);assert.equal(calls[0].url,path);assert.equal(calls[0].options.method,'POST');
    assert.equal(calls[0].options.headers['X-CSRF-Token'],'csrf');assert.deepEqual(JSON.parse(calls[0].options.body),data);
    assert.equal('success' in result,false);
  }
});

test('Lost or malformed submission receipt never retries the request',async()=>{
  for(const result of [null,{accepted:false,request_id,kind:'BACKUP',status_url:'/api/operation'},
      {accepted:true,request_id:'b'.repeat(32),kind:'BACKUP',status_url:'/api/operation'},
      {accepted:true,request_id,kind:'RESTORE',status_url:'/api/operation'},
      {accepted:true,request_id,kind:'BACKUP',status_url:'https://other.example/secret'}]){
    let calls=0;
    const client=new PanelClient({fetcher:async()=>{calls++;return {ok:true,json:async()=>result};}});client.csrf='csrf';
    await assert.rejects(client.startBackup({request_id,mode:'NEW',confirmed:true}),error=>error.status===502);
    assert.equal(calls,1);
  }
  let calls=0;
  const client=new PanelClient({fetcher:async()=>{calls++;throw Error('connection lost');}});client.csrf='csrf';
  await assert.rejects(client.startBackup({request_id,mode:'NEW',confirmed:true}));assert.equal(calls,1);
});

test('Missing request identity or CSRF makes no submission',async()=>{
  let calls=0;
  const client=new PanelClient({fetcher:async()=>{calls++;throw Error('unexpected');}});
  await assert.rejects(client.startBackup({mode:'NEW',confirmed:true}),error=>error.status===400);
  await assert.rejects(client.startBackup({request_id,mode:'NEW',confirmed:true}),error=>error.status===403);
  assert.equal(calls,0);
});
