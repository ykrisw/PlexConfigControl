import test from 'node:test';
import assert from 'node:assert/strict';
import {createSettingsController} from '../../plexconfigcontrol/static/settings-controller.mjs';
const initial={theme:'System',language:'en',timezone:'Europe/London'};

test('theme stays System until the server confirms a manual change',async()=>{
  const states=[],changes=[];let resolve,calls=0;
  const controller=createSettingsController({updateSettings:async change=>{
    calls++;assert.deepEqual(change,{theme:'Dark'});return new Promise(done=>{resolve=done;});
  }},initial,state=>states.push(state),next=>changes.push(next));
  const saving=controller.save('theme','Dark');
  assert.equal(states.at(-1).preferences.theme,'System');
  assert.equal(await controller.save('theme','Light'),false);assert.equal(calls,1);
  resolve({...initial,theme:'Dark'});assert.equal(await saving,true);
  assert.equal(states.at(-1).preferences.theme,'Dark');assert.equal(changes.length,1);
  controller.dispose();
});

test('failed save preserves preferences and no automatic retry occurs',async()=>{
  const states=[];let calls=0;
  const controller=createSettingsController({updateSettings:async()=>{calls++;throw Error('offline');}},initial,state=>states.push(state));
  assert.equal(await controller.save('language','pl'),false);
  assert.deepEqual(states.at(-1).preferences,initial);assert.equal(calls,1);
  assert.equal(states.at(-1).saved,false);controller.dispose();
});

test('late saves cannot redraw disposed views or apply a language after logout',async()=>{
  let resolve,changes=0;const states=[];
  const controller=createSettingsController({updateSettings:()=>new Promise(done=>{resolve=done;})},initial,state=>states.push(state),()=>changes++);
  const saving=controller.save('language','pl');controller.dispose();const count=states.length;
  resolve({...initial,language:'pl'});assert.equal(await saving,false);
  assert.equal(changes,0);assert.equal(states.length,count);
});
