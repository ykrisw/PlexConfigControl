// No session timeout: polling checks service state, never user inactivity.
export function createDashboardController(client, render, {
  onSignedOut = () => {}, schedule = setTimeout, cancel = clearTimeout, monitorPlex = true,
} = {}) {
  const lifecycle = new AbortController();
  const state = {plex: 'UNKNOWN', busy: false, error: ''};
  let timer, disposed = false;
  const emit = () => { if (!disposed) render({...state}); };
  async function poll() {
    let value = 'UNKNOWN';
    try {
      const result = await client.status(lifecycle.signal);
      if (result.available !== false && ['RUNNING', 'STOPPED'].includes(result.state)) value = result.state;
    } catch { /* Failed reads invalidate the previous service state. */ }
    if (disposed) return;
    state.plex = value; emit();
    timer = schedule(poll, 2000);
  }
  async function mutate(action, reason) {
    if (disposed || state.busy) return false;
    state.busy = true; state.error = ''; emit();
    try {
      const result=await action();
      if (!disposed) {
        dispose();
        onSignedOut(reason==='password_changed'&&result?.history_recorded===false?'password_changed_history_pending':reason);
      }
      return true;
    } catch (error) {
      if (!disposed) state.error = error.message || 'Request failed. Try again.';
      return false;
    } finally {
      state.busy = false; emit();
    }
  }
  function dispose() {
    disposed = true; lifecycle.abort(); cancel(timer);
  }
  emit(); if(monitorPlex) void poll();
  return {
    logout: () => mutate(() => client.logout(lifecycle.signal), 'logout'),
    changePassword(current, password, confirmation) {
      if (disposed || state.busy) return Promise.resolve(false);
      if (![current, password, confirmation].every(value => typeof value === 'string' && value.length > 0 && value.length <= 4096)) {
        state.error = 'All password fields are required'; emit(); return Promise.resolve(false);
      }
      if (password !== confirmation) {
        state.error = 'New passwords do not match'; emit(); return Promise.resolve(false);
      }
      return mutate(() => client.changePassword(current, password, confirmation, lifecycle.signal), 'password_changed');
    },
    dispose,
  };
}
