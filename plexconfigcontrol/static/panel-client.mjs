// Shared API connection for the approved panels. No DOM or theme changes.
export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error || `Request failed (${status})`);
    this.status = status;
    this.body = body;
  }
}

export class PanelClient {
  constructor({fetcher = globalThis.fetch, onSessionExpired = () => {}} = {}) {
    this.fetcher = fetcher;
    this.onSessionExpired = onSessionExpired;
    this.csrf = null;
  }

  async request(path, {body, signal, login = false} = {}) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    signal?.addEventListener('abort', abort, {once: true});
    const timer = setTimeout(abort, 15000);
    try {
      const headers = {Accept: 'application/json'};
      if (body !== undefined) {
        headers['Content-Type'] = 'application/json';
        if (login) headers['X-PCC-Request'] = '1';
        else {
          if (!this.csrf) throw new ApiError(403, {error: 'Sign in again before making changes'});
          headers['X-CSRF-Token'] = this.csrf;
        }
      }
      const response = await this.fetcher(path, {
        method: body === undefined ? 'GET' : 'POST', headers,
        credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        signal: controller.signal,
        ...(body === undefined ? {} : {body: JSON.stringify(body)}),
      });
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 401 && !login) {
          this.csrf = null;
          this.onSessionExpired();
        }
        throw new ApiError(response.status, result);
      }
      return result;
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

  async logout() {
    await this.request('/api/logout', {body: {}});
    this.csrf = null;
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
