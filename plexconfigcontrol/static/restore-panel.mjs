import {createSubmission} from './submission-controller.mjs';
// Behaviour for Restore controls; existing HTML/CSS remains responsible for layout.
export class RestoreController {
  constructor(client, render, {makeId}={}) {
    this.client = client;
    this.render = render;
    this.state = {selected: null, busy: false, snapshot: null, error: null};
    this.disposed = false;
    this.refreshSerial = 0;
    this.submission=createSubmission((request,signal)=>client.executeRestore(request,signal),
      (id,signal)=>client.executionStatus(id,signal),value=>{this.state.submission=value;this.emit();},
      {kind:'RESTORE',...(makeId?{makeId}:{})});
    this.state.submission=this.submission.view();
  }
  emit() { if (!this.disposed) this.render({...this.state}); }
  select(name) {
    const phase=this.state.snapshot?.operation?.operation?.phase;
    if (this.disposed || this.state.busy || this.submission.view().blocked || this.state.snapshot?.operation?.publication?.pending===true || ['VALIDATING','RUNNING','RECOVERY_REQUIRED','WAITING_FOR_PLEX_STOP','READY'].includes(phase)) return;
    this.state.selected = name || null;
    this.state.error = null;
    this.emit();
  }
  reconcileSelection(names) {
    if(this.disposed)return;
    if(this.state.selected&&!names.includes(this.state.selected)){
      this.state.selected=null;this.emit();
    }
  }
  async refresh(signal, force=false) {
    if(this.disposed||(this.state.busy&&!force))return;
    const serial=++this.refreshSerial;
    try {
      const snapshot = await this.client.restoreView(signal);
      if (this.disposed || serial!==this.refreshSerial) return;
      this.state.snapshot = snapshot;
      this.submission.observe(snapshot?.operation?.execution);
      this.state.error = null;
      this.emit();
    } catch (error) {
      if (signal?.aborted || this.disposed || serial!==this.refreshSerial) return;
      this.state.snapshot = null; // Never leave stale READY controls enabled.
      this.state.error = error.message;
      this.emit();
      if (error.status === 401) throw error;
    }
  }
  async validate() {
    const phase=this.state.snapshot?.operation?.operation?.phase;
    if (this.disposed || this.state.busy || this.submission.view().blocked || this.state.snapshot?.operation?.publication?.pending===true || !this.state.selected || ['VALIDATING','RUNNING','RECOVERY_REQUIRED','WAITING_FOR_PLEX_STOP','READY'].includes(phase)) return;
    this.refreshSerial++;
    this.state.busy = true;
    this.state.error = null;
    this.emit();
    try {
      await this.client.validateArchive(this.state.selected);
      await this.refresh(undefined,true);
    } catch (error) {
      // Never retry a POST automatically: the server may already own the job.
      this.state.snapshot = null;
      this.state.error = error.message;
    } finally {
      this.state.busy = false;
      this.emit();
    }
  }
  async cancel() {
    const operation=this.state.snapshot?.operation?.operation;
    if (this.disposed || this.state.busy || this.submission.view().blocked || operation?.outcome!=null || this.state.snapshot?.operation?.publication?.pending===true || operation?.kind!=='RESTORE' || !['WAITING_FOR_PLEX_STOP','READY'].includes(operation.phase)) return;
    this.refreshSerial++;
    this.state.busy = true;
    this.emit();
    try {
      await this.client.cancelRestore();
      await this.refresh(undefined,true);
    } catch (error) {
      this.state.snapshot = null;
      this.state.error = error.message;
    } finally {
      this.state.busy = false;
      this.emit();
    }
  }
  prepareExecution(){
    const snapshot=this.state.snapshot,operation=snapshot?.operation?.operation,readiness=snapshot?.readiness;
    if(this.disposed||this.state.busy||this.submission.view().blocked||snapshot?.capabilities?.restore_execute!==true||
      ['QUEUED','RUNNING','RECOVERY_REQUIRED'].includes(snapshot?.operation?.execution?.state)||
      snapshot?.operation?.publication?.pending===true||operation?.kind!=='RESTORE'||operation.outcome!=null||
      operation.snapshot_id||!['WAITING_FOR_PLEX_STOP','READY'].includes(operation.phase)||
      readiness?.ready!==true||readiness.plex?.state!=='STOPPED'||readiness.plex?.available===false||
      operation.validation_details?.status!=='VALID'||readiness.archive!==operation.validation_details.archive||
      this.state.selected!==readiness.archive||operation.archive_identity!==operation.validation_details.sha256||
      !/^[0-9a-f]{64}$/.test(operation.archive_identity))return null;
    return {archive:readiness.archive,sha256:operation.archive_identity};
  }
  async execute(confirmed,confirmation){
    if(this.disposed||this.state.busy||this.submission.view().blocked)return false;
    const current=this.prepareExecution();
    if(!current||confirmation!=='RESTORE'||current.archive!==confirmed?.archive||current.sha256!==confirmed?.sha256){
      this.state.error='Restore confirmation changed. Refresh and confirm again.';this.emit();return false;
    }
    const result=await this.submission.submit({...current,confirmation:'RESTORE'});
    try{await this.refresh(undefined,true);}catch{}return result;
  }
  async retrySubmission(){const result=await this.submission.retry();try{await this.refresh(undefined,true);}catch{}return result;}
  checkSubmission(){return this.submission.check();}
  startPolling(interval = 1500) {
    if (this.poller || this.disposed) return;
    this.poller = new AbortController();
    const signal = this.poller.signal;
    const tick = async () => {
      try { await this.refresh(signal); }
      catch { return; } // A rejected session requires sign-in, not more polling.
      if (!signal.aborted) this.timer = setTimeout(tick, interval);
    };
    void tick();
  }
  dispose() {
    this.disposed = true;
    this.submission.dispose();
    this.poller?.abort();
    clearTimeout(this.timer);
    // Leaving a tab does not cancel server work or stop/start Plex.
  }
}

export function bindRestoreControls(root, client, render) {
  const controller = new RestoreController(client, render);
  const events = new AbortController();
  root.addEventListener('change', event => {
    if (event.target.matches('input[name="restore-archive"]') && event.target.checked) {
      controller.select(event.target.value);
    }
  }, {signal: events.signal});
  root.addEventListener('click', event => {
    const action = event.target.closest('[data-restore-action]');
    if (!action || !root.contains(action) || action.disabled) return;
    const name = action.dataset.restoreAction;
    if (name === 'validate') void controller.validate();
    if (name === 'cancel') void controller.cancel();
    if (name === 'refresh') void controller.refresh();
  }, {signal: events.signal});
  controller.emit();
  controller.startPolling();
  const dispose=() => { events.abort(); controller.dispose(); };
  dispose.reconcileSelection=names=>controller.reconcileSelection(names);
  dispose.prepareExecution=()=>controller.prepareExecution();
  dispose.execute=(confirmed,text)=>controller.execute(confirmed,text);
  dispose.retrySubmission=()=>controller.retrySubmission();
  dispose.checkSubmission=()=>controller.checkSubmission();
  return dispose;
}
