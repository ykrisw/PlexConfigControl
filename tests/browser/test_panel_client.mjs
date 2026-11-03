import test from 'node:test';
import assert from 'node:assert/strict';
import {PanelClient, ApiError} from '../../plexconfigcontrol/static/panel-client.mjs';

function setup(responses) {
  const calls=[];
  const client=new PanelClient({fetcher: async (path, options) => {
    calls.push({path, options});
    const [status,body]=responses.shift();
    return {status,ok:status>=200 && status<300,json:async () => body};
  }});
  return {client,calls};
}

test('sign-in and background validation send CSRF with same-origin cookies', async () => {
  const {client,calls}=setup([[200,{authenticated:true,csrf:'token'}],[202,{accepted:true}]]);
  await client.login('password');
  await client.validateArchive('selected.tar.gz');
  assert.equal(calls[0].options.headers['X-PCC-Request'],'1');
  assert.equal(calls[1].options.headers['X-CSRF-Token'],'token');
  assert.equal(calls[1].options.credentials,'same-origin');
  assert.deepEqual(JSON.parse(calls[1].options.body),{archive:'selected.tar.gz',background:true});
});

test('validation view does not contend for readiness lock while validating', async () => {
  const {client,calls}=setup([[200,{operation:{phase:'VALIDATING'},progress:{stage:'READING_ARCHIVE'}}]]);
  const view=await client.restoreView();
  assert.equal(view.readiness,null); assert.equal(calls.length,1);
});

test('waiting view checks actual readiness without assuming stopped Plex', async () => {
  const {client,calls}=setup([[200,{operation:{phase:'WAITING_FOR_PLEX_STOP'}}],
    [200,{ready:false,reason:'STOP_PLEX_MANUALLY'}]]);
  const view=await client.restoreView();
  assert.equal(view.readiness.ready,false);
  assert.equal(calls[1].path,'/api/restore/readiness');
});

test('unauthorized response clears CSRF and notifies sign-in screen', async () => {
  const {client}=setup([[401,{error:'Sign in required'}]]);
  let expired=0; client.csrf='old'; client.onSessionExpired=() => expired++;
  await assert.rejects(client.operation(),error => error instanceof ApiError && error.status===401);
  assert.equal(client.csrf,null); assert.equal(expired,1);
});

test('changes without a CSRF token never reach the server', async () => {
  const {client,calls}=setup([]);
  await assert.rejects(client.validateArchive('archive'),ApiError);
  assert.equal(calls.length,0);
});

test('page reload restores an existing session without asking for password', async () => {
  const {client,calls}=setup([[200,{authenticated:true,csrf:'existing'}],[200,{cancelled:true}]]);
  await client.restoreSession();
  await client.cancelRestore();
  assert.equal(calls[0].path,'/api/session');
  assert.equal(calls[0].options.method,'GET');
  assert.equal(calls[1].options.headers['X-CSRF-Token'],'existing');
});
