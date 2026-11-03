import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeOutcome,backupResult,recoveryOutcome} from '../../plexconfigcontrol/static/operation-outcome.mjs';
const archive='TrueNASPlexConfig_2026.11.03_12.00.00.tar.gz';
const outcome=code=>({code,archive});
const snapshot=()=>({operation:{kind:'BACKUP',phase:'SUCCESS',snapshot_id:null,outcome:outcome('BACKUP_COMPLETED')},
  publication:{pending:false,status:'NONE',archive:null,temporary_file:null},
  progress:{operation:'BACKUP',stage:'COMPLETED',active:false,finished:100}});

test('success needs consistent operation progress and completed cleanup, never an archive list alone',()=>{
  assert.match(backupResult(snapshot()),/Last Backup completed successfully/);
  for(const mutate of [s=>s.operation.phase='RUNNING',s=>s.operation.phase='RECOVERY_REQUIRED',
    s=>s.operation.snapshot_id='retained',s=>delete s.operation.snapshot_id,
    s=>s.progress.stage='CLEANUP_REQUIRED',s=>s.progress.active=true,s=>s.progress.finished=null,
    s=>s.progress.operation='RESTORE',s=>s.publication.pending=true,s=>s.publication.status='VERIFICATION_REQUIRED',
    s=>s.publication.archive=archive,s=>s.operation.outcome=null]){
    const value=snapshot();mutate(value);assert.equal(backupResult(value),'');
  }
  assert.equal(backupResult({archives:[{name:archive}]}),'');
});

test('published and ambiguous failures never become success and are translated',()=>{
  const published={kind:'BACKUP',phase:'RECOVERY_REQUIRED',outcome:outcome('BACKUP_PUBLISHED_REVIEW')};
  assert.match(recoveryOutcome(published),/not a successful Backup/);
  assert.match(recoveryOutcome(published,'pl'),/Backup nie zakończył się sukcesem/);
  assert.match(recoveryOutcome({...published,outcome:outcome('BACKUP_PUBLICATION_UNCERTAIN')}),/could not be confirmed/);
  assert.equal(backupResult({...snapshot(),operation:{...snapshot().operation,...published}}),'');
});

test('failed and reconciled operations remain failed in English and Polish',()=>{
  for(const code of ['BACKUP_FAILED','BACKUP_RECONCILED']){
    const value=snapshot();value.operation.phase='FAILED';value.operation.outcome=outcome(code);value.progress.stage='FAILED';
    assert.ok(backupResult(value));assert.ok(backupResult(value,'pl'));
    assert.doesNotMatch(backupResult(value),/completed successfully/);
  }
  const value=snapshot();value.operation.phase='FAILED';value.operation.outcome=outcome('BACKUP_RECONCILED');
  assert.match(backupResult(value),/original Backup remains FAILED/);
});

test('malformed unknown or unrelated outcomes cannot publish arbitrary strings',()=>{
  for(const value of [{code:'secret',archive},outcome('UNKNOWN'),{...outcome('BACKUP_COMPLETED'),extra:'secret'},
    {code:'BACKUP_FAILED',archive:'<script>secret</script>'},[],{code:'BACKUP_COMPLETED',archive:null},{code:'BACKUP_FAILED',archive:archive+'\n'}]){
    assert.equal(normalizeOutcome(value),undefined);
    assert.equal(backupResult({...snapshot(),operation:{...snapshot().operation,outcome:value}}),'');
  }
  assert.equal(recoveryOutcome({kind:'RESTORE',phase:'RECOVERY_REQUIRED',outcome:outcome('BACKUP_FAILED')}),'');
  assert.equal(normalizeOutcome(undefined),null);
});

test('interrupted historical results cannot be reused as active or successful completion',()=>{
  const data={kind:'BACKUP',phase:'RECOVERY_REQUIRED',outcome:{code:'BACKUP_INTERRUPTED',archive:null}};
  assert.match(recoveryOutcome(data,'pl'),/Backup został przerwany/);
  assert.equal(backupResult({...snapshot(),operation:{...snapshot().operation,outcome:data.outcome}}),'');
  assert.equal(recoveryOutcome({...data,phase:'RUNNING'}),'');
});
