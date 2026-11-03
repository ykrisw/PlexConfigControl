import test from 'node:test';
import assert from 'node:assert/strict';
import {createPhotoController} from '../../plexconfigcontrol/static/photo-controller.mjs';
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const present={present:true,revision:'a'.repeat(64)};
const absent={present:false,revision:null};

test('invalid and oversized photos never upload or replace the existing picture',async()=>{
  let uploads=0;const states=[];
  const controller=createPhotoController({photoStatus:async()=>present,uploadPhoto:async()=>uploads++},state=>states.push(state));
  await flush();
  assert.equal(await controller.upload({type:'image/svg+xml',size:10}),false);
  assert.equal(await controller.upload({type:'image/png',size:6*1024*1024}),false);
  assert.equal(uploads,0);assert.equal(states.at(-1).revision,present.revision);controller.dispose();
});

test('only confirmed server changes replace the picture; duplicate uploads are blocked',async()=>{
  let finish,calls=0;const states=[];
  const controller=createPhotoController({photoStatus:async()=>absent,uploadPhoto:()=>{calls++;return new Promise(resolve=>{finish=resolve;});}},state=>states.push(state));
  await flush();const file=new Blob(['photo'],{type:'image/png'}),pending=controller.upload(file);
  assert.equal(await controller.upload(file),false);assert.equal(calls,1);assert.equal(states.at(-1).present,false);
  finish(present);assert.equal(await pending,true);assert.equal(states.at(-1).revision,present.revision);controller.dispose();
});

test('removal requires confirmation and sends the displayed revision',async()=>{
  const revisions=[],states=[];
  const controller=createPhotoController({photoStatus:async()=>present,removePhoto:async revision=>{revisions.push(revision);return absent;}},state=>states.push(state));
  await flush();assert.equal(await controller.remove(false),false);assert.deepEqual(revisions,[]);
  assert.equal(await controller.remove(true),true);assert.deepEqual(revisions,[present.revision]);
  assert.equal(states.at(-1).present,false);controller.dispose();
});

test('failed uploads preserve the old photo and late replies cannot redraw after logout',async()=>{
  const states=[];let finish;
  const client={photoStatus:async()=>present,uploadPhoto:async()=>{throw Error('offline');}};
  const controller=createPhotoController(client,state=>states.push(state));await flush();
  const file=new Blob(['photo'],{type:'image/png'});assert.equal(await controller.upload(file),false);
  assert.equal(states.at(-1).revision,present.revision);
  client.uploadPhoto=()=>new Promise(resolve=>{finish=resolve;});const pending=controller.upload(file);
  controller.dispose();const count=states.length;finish(absent);assert.equal(await pending,false);assert.equal(states.length,count);
});
