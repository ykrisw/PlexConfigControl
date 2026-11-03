import test from 'node:test';
import assert from 'node:assert/strict';
import {restorePresentation,restoreError} from '../../plexconfigcontrol/static/restore-messages.mjs';

function state(phase='WAITING_FOR_PLEX_STOP',reason='STOP_PLEX_MANUALLY'){
  return {selected:'chosen',busy:false,error:null,snapshot:{operation:{operation:{kind:'RESTORE',phase,validation_details:{status:'VALID'}},progress:null},
    readiness:{ready:false,reason,plex:{state:'RUNNING',available:true}}}};
}

test('Polish wait message asks for manual stop and keeps validation disabled',()=>{
  const view=restorePresentation(state(),'pl');
  assert.match(view.notice,/Zatrzymaj Plex ręcznie/);assert.match(view.notice,/będzie czekał/);
  assert.equal(view.validateDisabled,true);assert.equal(view.cancelVisible,true);
});

test('lost or contradictory Plex state never claims stopped readiness',()=>{
  const source=state('READY','PLEX_STOP_NOT_CONFIRMED');
  source.snapshot.readiness.ready=true;
  assert.match(restorePresentation(source,'pl').notice,/Nie potwierdzono/);
  source.snapshot.readiness={ready:true,reason:null,plex:{state:'STOPPED',available:true}};
  const view=restorePresentation(source,'pl');
  assert.match(view.notice,/Plex zatrzymany/);assert.match(view.notice,/nie jest jeszcze podłączone/);
  assert.equal(view.validateDisabled,true);
});

test('known validation failures translate their specific reason and unknown reasons stay visible',()=>{
  const source=state('FAILED');source.snapshot.operation.operation.validation_details={status:'FAILED',reason:'Required Plex files missing'};
  assert.equal(restorePresentation(source,'pl').notice,'Brak wymaganych plików konfiguracji Plex.');
  assert.match(restoreError('Future diagnostic reason','pl'),/Future diagnostic reason/);
  assert.equal(restoreError('Corrupt or unreadable archive','en'),'Corrupt or unreadable archive');
});

test('hashing progress displays actual bytes and elapsed time, never invented percentages',()=>{
  const source=state('VALIDATING');source.snapshot.operation.progress={stage:'HASHING_ARCHIVE',done:1048576,elapsed_seconds:12.9};
  const view=restorePresentation(source,'pl');
  assert.match(view.progressText,/Obliczanie sumy kontrolnej/);
  assert.match(view.progressText,/12 s/);assert.doesNotMatch(view.progressText,/%/);
  assert.equal(view.selectionDisabled,true);assert.equal(view.cancelVisible,false);
});


test('pending publication blocks restore controls even at FAILED or READY checkpoints',()=>{
  for(const phase of ['FAILED','READY']){
    const source=state(phase);source.snapshot.operation.publication={pending:true};
    const view=restorePresentation(source,'pl');
    assert.equal(view.validateDisabled,true);assert.equal(view.selectionDisabled,true);
    assert.equal(view.cancelVisible,false);assert.match(view.notice,/odzyskiwanie/);
  }
});

test('execution preparing before snapshot is active rather than a manual-stop wait',()=>{
  const source=state('READY');source.snapshot.operation.operation.outcome={code:'RESTORE_IN_PROGRESS',archive:'TrueNASPlexConfig_2026.11.03_12.00.00.tar.gz'};
  source.snapshot.operation.progress={operation:'RESTORE',stage:'RESTORING',active:true,done:0,total:null,elapsed_seconds:17.8};
  const view=restorePresentation(source,'pl');
  assert.equal(view.waiting,false);assert.equal(view.active,true);assert.equal(view.cancelVisible,false);
  assert.match(view.notice,/Restore jest w toku/);assert.match(view.progressText,/Przywracanie konfiguracji · 17 s/);
  assert.doesNotMatch(view.progressText,/bytes|bajt|%/);
});
