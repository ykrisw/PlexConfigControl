import test from 'node:test';
import assert from 'node:assert/strict';
const {RestoreController}=await import(new URL('file://'+process.env.PCC_QNAP_SOURCE+'/plexconfigcontrol/static/restore-panel.mjs'));

test('a stale resumable archive never overwrites an explicit newer selection',()=>{
 const c=new RestoreController({},()=>{});
 c.state.selected='PlexConfig_new.tar.gz';
 c.state.snapshot={operation:{operation:{kind:'RESTORE',phase:'READY',validation_details:{status:'VALID',archive:'PlexConfig_old.tar.gz'}}},readiness:{archive:'PlexConfig_old.tar.gz'}};
 c.reconcileSelection(['PlexConfig_new.tar.gz']);
 assert.equal(c.state.selected,'PlexConfig_new.tar.gz');c.dispose();
});
test('validation refuses a visible selection different from controller state',async()=>{
 let calls=0;const c=new RestoreController({validateArchive:async()=>calls++},()=>{});
 c.state.selected='PlexConfig_old.tar.gz';
 await c.validate('PlexConfig_new.tar.gz');assert.equal(calls,0);
 assert.match(c.state.error,/selection changed/);c.dispose();
});
