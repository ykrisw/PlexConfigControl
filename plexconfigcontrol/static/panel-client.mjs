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
  }

  async request(path, {body, raw, signal, login = false, download = false} = {}) {
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
      if (!response.ok) {
        if (response.status === 401 && !login) {
          this.csrf = null;
          this.onSessionExpired();
        }
        const result = await response.json();
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
        if (blob.size > 34 * 1024 * 1024) throw new ApiError(502, {error: 'Log download is too large'});
        return {filename: match[1], blob};
      }
      return await response.json();
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  }

  async login(password) {
    this.csrf = null;
    const result = await this.request('/api/login', {body: {password}, login: true});
    if (!result.authenticated || typeof result.csrf !== 'string' || !result.csrf) {
      throw new ApiError(502, {error: 'Invalid sign-in response'});
    }
    this.csrf = result.csrf; // Memory only; password and token are never logged.
    return result;
  }

  async logout(signal) {
    const result = await this.request('/api/logout', {body: {}, signal});
    if (result.authenticated !== false) throw new ApiError(502, {error: 'Sign-out could not be confirmed'});
    this.csrf = null;
  }

  async changePassword(current, password, confirmation, signal) {
    const result = await this.request('/api/account/password', {body: {
      current_password: current, new_password: password,
      confirm_new_password: confirmation,
    }, signal});
    if (result.changed !== true || result.sign_in_required !== true) {
      throw new ApiError(502, {error: 'Password change could not be confirmed'});
    }
    this.csrf = null;
    return result;
  }

  settings(signal) { return this.request('/api/settings', {signal}); }
  photoStatus(signal) { return this.request('/api/account/photo/status',{signal}); }
  uploadPhoto(file,signal) { return this.request('/api/account/photo',{raw:file,signal}); }
  removePhoto(revision,signal) { return this.request('/api/account/photo/remove',{body:{confirmed:true,revision},signal}); }
  updateSettings(changes,signal) { return this.request('/api/settings', {body:changes,signal}); }
  integration(signal) { return this.request('/api/integration', {signal}); }
  capabilities(signal) { return this.request('/api/capabilities', {signal}); }
  backupPlan(signal) { return this.request('/api/backup/plan', {signal}); }
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

  async restoreSession() {
    this.csrf = null;
    const result = await this.request('/api/session');
    if (!result.authenticated || typeof result.csrf !== 'string' || !result.csrf) {
      throw new ApiError(502, {error: 'Invalid session response'});
    }
    this.csrf = result.csrf;
    return result;
  }

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
    const readiness = ['WAITING_FOR_PLEX_STOP', 'READY'].includes(phase)
      ? await this.readiness(signal) : null;
    return {operation, readiness};
  }
}
