import test from 'node:test';
import assert from 'node:assert/strict';
import {PanelClient,ApiError} from '../../plexconfigcontrol/static/panel-client.mjs';
const reply=(status,body)=>({status,ok:status>=200&&status<300,json:async()=>body});
const flush=()=>new Promise(done=>setImmediate(done));

test('late unauthorized response from a previous session cannot log out a fresh login',async()=>{
  let release,expired=0;
  const client=new PanelClient({onSessionExpired:()=>expired++,fetcher:async path=>path==='/api/login'?
    reply(200,{authenticated:true,csrf:'fresh'}):new Promise(done=>release=done)});
  client.csrf='old';const old=client.status();const rejected=assert.rejects(old,error=>error instanceof ApiError&&error.status===409);
  await client.login('password');release(reply(401,{error:'Sign in required'}));await rejected;
  assert.equal(client.csrf,'fresh');assert.equal(expired,0);
});

test('concurrent unauthorized responses expire a session once',async()=>{
  let expired=0;const releases=[];
  const client=new PanelClient({onSessionExpired:()=>expired++,fetcher:()=>new Promise(done=>releases.push(done))});
  client.csrf='old';const requests=Promise.allSettled([client.status(),client.operation()]);
  releases[0](reply(401,{}));await flush();releases[1](reply(401,{}));
  const values=await requests;assert.ok(values.every(value=>value.status==='rejected'));
  assert.equal(expired,1);assert.equal(client.csrf,null);
});

test('late successful JSON body cannot be delivered after the session changed',async()=>{
  let body;const client=new PanelClient({fetcher:async path=>path==='/api/login'?
    reply(200,{authenticated:true,csrf:'fresh'}):{ok:true,status:200,json:()=>new Promise(done=>body=done)}});
  const previous=client.status();const rejected=assert.rejects(previous,error=>error.status===409);await flush();
  await client.login('password');body({state:'RUNNING',available:true});await rejected;assert.equal(client.csrf,'fresh');
});

test('background unauthorized polling cannot abort a confirmed password change',async()=>{
  let passwordReply,expired=0;
  const client=new PanelClient({onSessionExpired:()=>expired++,fetcher:async path=>path==='/api/account/password'?
    new Promise(done=>passwordReply=done):reply(401,{error:'Sign in required'})});
  client.csrf='old';const changing=client.changePassword('old','new','new');
  await assert.rejects(client.status(),error=>error.status===401);
  assert.equal(expired,0);assert.equal(client.csrf,'old');
  passwordReply(reply(200,{changed:true,sign_in_required:true}));await changing;
  assert.equal(client.csrf,null);assert.equal(expired,0);
});

test('failed password request plus confirmed unauthorized polling returns to sign in',async()=>{
  let fail,expired=0;
  const client=new PanelClient({onSessionExpired:()=>expired++,fetcher:async path=>path==='/api/account/password'?
    new Promise((resolve,reject)=>fail=reject):reply(401,{})});
  client.csrf='old';const changing=client.changePassword('old','new','new');const rejected=assert.rejects(changing);
  await assert.rejects(client.status());fail(Error('connection lost'));await rejected;
  assert.equal(expired,1);assert.equal(client.csrf,null);
});

test('authentication actions are serialized without duplicate requests or automatic retries',async()=>{
  let release,calls=0;
  const client=new PanelClient({fetcher:()=>{calls++;return new Promise(done=>release=done);}});
  const login=client.login('password');await assert.rejects(client.restoreSession(),error=>error.status===409);
  await assert.rejects(client.logout(),error=>error.status===409);assert.equal(calls,1);
  release(reply(200,{authenticated:true,csrf:'fresh'}));await login;assert.equal(client.csrf,'fresh');
});
