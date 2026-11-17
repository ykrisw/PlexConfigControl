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

const labels=await import(new URL('file://'+process.env.PCC_QNAP_SOURCE+'/plexconfigcontrol/static/archive-labels.mjs'));
test('ANOTHER backup never labels new TEST01 with the previous UDANY archive',()=>{
 const submission={request_id:'new',archive:'UDANY_old.tar.gz',phase:'SENDING'};
 assert.equal(labels.backupSubmission({submission,operation:{execution:{kind:'BACKUP',request_id:'new'},operation:{execution_request_id:'old',outcome:{archive:'UDANY_old.tar.gz'}}}}).archive,null);
 assert.equal(labels.backupSubmission({submission,operation:{execution:{kind:'BACKUP',request_id:'old'},operation:{outcome:{archive:'UDANY_old.tar.gz'}}}}).archive,null);
 assert.equal(labels.backupSubmission({submission,operation:{execution:{kind:'BACKUP',request_id:'new'},operation:{execution_request_id:'new',outcome:{archive:'TEST01_new.tar.gz'}}}}).archive,'TEST01_new.tar.gz');
});
test('full archive name precedes validation and restore progress in either language',()=>{
 for(const text of ['Weryfikacja archiwum · 140 s','Oczekiwanie na stan przywracania…','Validating archive · 140 s','Waiting for restore status…']){
  const state={snapshot:{operation:{operation:{kind:'RESTORE'},progress:{archive:'TEST01_2026.11.17_19.00.00.tar.gz'}}}};
  assert.equal(labels.archiveProgress(labels.restoreProgressName(state),text),'TEST01_2026.11.17_19.00.00.tar.gz — '+text);
 }
 assert.equal(labels.restoreProgressName({busy:true,selected:'TEST01_new.tar.gz',snapshot:{operation:{operation:{kind:'RESTORE'},progress:{archive:'UDANY_old.tar.gz'}}}}),'TEST01_new.tar.gz');
});
