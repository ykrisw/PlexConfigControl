// Shared API connection for the approved panels. No DOM or theme changes.
export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error || `Request failed (${status})`);
    this.status = status;
    this.body = body;
  }
}

export class PanelClient {
  constructor({fetcher = (...args) => globalThis.fetch(...args), onSessionExpired = () => {}} = {}) {
    this.fetcher = fetcher;
    this.onSessionExpired = onSessionExpired;
    this.csrf = null;
    this.sessionEpoch=0;this.transition=false;this.authPending=false;this.deferredUnauthorized=false;
  }

  invalidateSession(){this.csrf=null;this.sessionEpoch++;}
  assertCurrent(epoch){if(epoch!==this.sessionEpoch)throw new ApiError(409,{error:'Session changed; refresh before continuing'});}
  expireSession(){this.invalidateSession();this.onSessionExpired();}

  async request(path, {body, raw, signal, login = false, download = false} = {}) {
    const epoch=this.sessionEpoch;
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    signal?.addEventListener('abort', abort, {once: true});
    // Diagnostics may perform two separately bounded 10-second reads.
    const timer = setTimeout(abort, path === '/api/integration' ? 30000 : 15000);
    try {
      const headers = {Accept: download ? 'application/zip, text/plain, application/json' : 'application/json'};
      if(body!==undefined&&raw!==undefined)throw new ApiError(400,{error:'Choose one request body'});
      const writing=body!==undefined||raw!==undefined;
      if (writing) {
        headers['Content-Type'] = raw!==undefined?'application/octet-stream':'application/json';
        if (login) headers['X-PCC-Request'] = '1';
        else {
          if (!this.csrf) throw new ApiError(403, {error: 'Sign in again before making changes'});
          headers['X-CSRF-Token'] = this.csrf;
        }
      }
      const response = await this.fetcher(path, {
        method: writing ? 'POST' : 'GET', headers,
        credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        signal: controller.signal,
        ...(writing ? {body:raw!==undefined?raw:JSON.stringify(body)} : {}),
      });
      this.assertCurrent(epoch);
      if (!response.ok) {
        let expiredHere=false;
        if (response.status === 401 && !login) {
          if(this.transition&&!['/api/account/password','/api/logout'].includes(path))this.deferredUnauthorized=true;
          else {this.expireSession();expiredHere=true;}
        }
        const result = await response.json();
        if(!expiredHere)this.assertCurrent(epoch);
        throw new ApiError(response.status, result);
      }
      if (download) {
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = /^attachment; filename="(Event_[1-9][0-9]*\.log|PlexConfigControl_Logs\.zip)"$/.exec(disposition);
        const type = (response.headers.get('Content-Type') || '').split(';')[0];
        if (!match || !['application/zip', 'text/plain'].includes(type)) {
          throw new ApiError(502, {error: 'Invalid log download response'});
        }
        const blob = await response.blob();
        this.assertCurrent(epoch);
        if (blob.size > 34 * 1024 * 1024) throw new ApiError(502, {error: 'Log download is too large'});
        return {filename: match[1], blob};
      }
      const result=await response.json();
      this.assertCurrent(epoch);
      return result;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  }

  async authenticate(action){
    if(this.transition||this.authPending)throw new ApiError(409,{error:'Account action is already in progress'});
    this.authPending=true;this.invalidateSession();const epoch=this.sessionEpoch;
    try{
      const result=await action();this.assertCurrent(epoch);
      if(result.authenticated!==true||typeof result.csrf!=='string'||!result.csrf)
        throw new ApiError(502,{error:'Invalid sign-in response'});
      this.csrf=result.csrf;return result;
    }finally{this.authPending=false;}
  }

  login(password){return this.authenticate(()=>this.request('/api/login',{body:{password},login:true}));}

  async endSession(action,valid,message){
    if(this.transition||this.authPending)throw new ApiError(409,{error:'Account action is already in progress'});
    this.transition=true;this.deferredUnauthorized=false;const epoch=this.sessionEpoch;
    try{
      const result=await action();this.assertCurrent(epoch);
      if(!valid(result))throw new ApiError(502,{error:message});
      this.invalidateSession();return result;
    }finally{
      this.transition=false;
      if(this.deferredUnauthorized&&epoch===this.sessionEpoch)this.expireSession();
      this.deferredUnauthorized=false;
    }
  }

  logout(signal){
    return this.endSession(()=>this.request('/api/logout',{body:{},signal}),
      result=>result.authenticated===false,'Sign-out could not be confirmed');
  }

  changePassword(current,password,confirmation,signal){
    return this.endSession(()=>this.request('/api/account/password',{body:{
      current_password:current,new_password:password,confirm_new_password:confirmation},signal}),
      result=>result.changed===true&&result.sign_in_required===true,'Password change could not be confirmed');
  }

  settings(signal) { return this.request('/api/settings', {signal}); }
  photoStatus(signal) { return this.request('/api/account/photo/status',{signal}); }
  uploadPhoto(file,signal) { return this.request('/api/account/photo',{raw:file,signal}); }
  removePhoto(revision,signal) { return this.request('/api/account/photo/remove',{body:{confirmed:true,revision},signal}); }
  updateSettings(changes,signal) { return this.request('/api/settings', {body:changes,signal}); }
  integration(signal) { return this.request('/api/integration', {signal}); }
  capabilities(signal) { return this.request('/api/capabilities', {signal}); }
  executionStatus(request_id,signal) {
    return this.request('/api/execution/status?request_id='+encodeURIComponent(request_id),{signal});
  }
  backupPlan(signal) { return this.request('/api/backup/plan', {signal}); }
  async submitOperation(path, kind, request, signal) {
    const expected=request?.request_id;
    if(typeof expected!=='string'||!/^[0-9a-f]{32}$/.test(expected))throw new ApiError(400,{error:'Operation request identity is required'});
    const result=await this.request(path,{body:request,signal});
    if(result?.accepted!==true||result.request_id!==expected||result.kind!==kind||result.status_url!=='/api/operation'){
      throw new ApiError(502,{error:'Submission could not be confirmed. Check operation status before retrying.'});
    }
    return {accepted:true,request_id:expected,kind,status_url:'/api/operation'};
  }
  startBackup(request, signal) {
    return this.submitOperation('/api/backup/start','BACKUP',request,signal);
  }
  executeRestore(request, signal) {
    return this.submitOperation('/api/restore/execute','RESTORE',request,signal);
  }
  deleteArchives(archives,signal) {
    return this.request('/api/archives/delete',{body:{archives,confirmed:true},signal});
  }
  history(signal) { return this.request('/api/history', {signal}); }
  clearHistory(ids, signal) {
    return this.request('/api/history/clear', {body: {ids, confirmed: true}, signal});
  }
  downloadHistory(ids, signal) {
    return this.request('/api/history/download', {body: {ids}, signal, download: true});
  }

  restoreSession(){return this.authenticate(()=>this.request('/api/session'));}

  validateArchive(archive, signal) {
    return this.request('/api/restore/validate', {body: {archive, background: true}, signal});
  }
  cancelRestore(signal) {
    return this.request('/api/restore/cancel', {body: {}, signal});
  }
  recovery(signal) { return this.request('/api/recovery', {signal}); }
  operation(signal) { return this.request('/api/operation', {signal}); }
  archives(signal) { return this.request('/api/archives', {signal}); }
  status(signal) { return this.request('/api/status', {signal}); }
  readiness(signal) { return this.request('/api/restore/readiness', {signal}); }

  async restoreView(signal) {
    const operation = await this.operation(signal);
    // Validation owns the operation lock. Do not query readiness until it ends.
    const phase = operation.operation.phase;
    const admitted=['QUEUED','RUNNING','RECOVERY_REQUIRED'].includes(operation.execution?.state);
    const readiness = ['WAITING_FOR_PLEX_STOP', 'READY'].includes(phase)&&!admitted
      ? await this.readiness(signal) : null;
    const capabilities=await this.capabilities(signal);
    return {operation, readiness, capabilities};
  }
}
