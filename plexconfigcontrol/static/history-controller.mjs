export function createHistoryController(client, render, {
  schedule = setTimeout, cancel = clearTimeout,
} = {}) {
  let entries = [], selected = new Set(), filter = 'ALL';
  let loading = false, busy = false, available = false, disposed = false, timer;
  let error = '', notice = '', archiveLogs = null, archiveCount = null, verifiedCount = null;
  const lifecycle = new AbortController();
  function emit() {
    if (disposed) return;
    render({entries: entries.filter(row => filter === 'ALL' || row.kind === filter),
      selected: [...selected], filter, loading, busy, available, error, notice, archiveLogs, archiveCount, verifiedCount,
      counts: {all: entries.length, backup: entries.filter(x => x.kind === 'BACKUP').length,
        restore: entries.filter(x => x.kind === 'RESTORE').length,
        success: entries.filter(x => x.status === 'SUCCESS').length,
        failed: entries.filter(x => x.status === 'FAILED').length}});
  }
  async function refresh() {
    if (disposed || loading || busy) return;
    cancel(timer); loading = true; emit();
    try {
      const rows = await client.history(lifecycle.signal);
      if (disposed) return;
      if (!Array.isArray(rows) || rows.some(row => !Number.isSafeInteger(row.id) || row.id <= 0)) throw Error('Invalid history response');
      entries = rows;
      archiveLogs = null;
      archiveCount = null;
      verifiedCount = null;
      if (typeof client.archives === 'function') {
        try {
          const archives = await client.archives(lifecycle.signal, {verification: true});
          if (disposed) return;
          if (Array.isArray(archives)) {
            archiveCount = archives.length;
            if (archives.every(item => typeof item?.verified === 'boolean'))
              verifiedCount = archives.filter(item => item.verified).length;
          }
        } catch {
          if (disposed) return;
        }
      }
      if(typeof client.operation==='function'){
        try{
          const operation=await client.operation(lifecycle.signal);
          if(disposed)return;
          const logging=operation?.archive_discovery;
          if(Number.isSafeInteger(logging?.pending_logs)&&logging.pending_logs>=0&&typeof logging.permanent_logs_enabled==='boolean')
            archiveLogs={pending:logging.pending_logs,enabled:logging.permanent_logs_enabled};
        }catch{if(disposed)return;}
      }
      const ids = new Set(rows.map(row => row.id));
      selected = new Set([...selected].filter(id => ids.has(id)));
      available = true; error = '';
    } catch (failure) {
      if (!disposed) { available = false; archiveCount = null; verifiedCount = null; error = failure.message || 'History unavailable'; }
    } finally {
      loading = false; emit();
      if (!disposed) timer = schedule(refresh, 5000);
    }
  }
  const chosen = () => [...selected].sort((a,b) => a-b);
  function selection(ids, limit) {
    return Array.isArray(ids) && ids.length > 0 && ids.length <= limit &&
      JSON.stringify([...ids].sort((a,b) => a-b)) === JSON.stringify(chosen());
  }
  async function action(ids, deleting) {
    if (disposed || busy || loading || !available) return null;
    if (!selection(ids, deleting ? 10000 : 1000)) {
      error = 'Selection changed or exceeds the limit. Select events again.'; emit(); return null;
    }
    busy = true; error = ''; notice = ''; cancel(timer); emit();
    try {
      if (!deleting) {
        const result = await client.downloadHistory([...ids], lifecycle.signal);
        return disposed ? null : result;
      }
      const result = await client.clearHistory([...ids], lifecycle.signal);
      if (disposed) return null;
      if (!Array.isArray(result.cleared) || JSON.stringify([...result.cleared].sort((a,b)=>a-b)) !== JSON.stringify([...ids].sort((a,b)=>a-b))) throw Error('History deletion could not be confirmed');
      const removed = new Set(ids);
      entries = entries.filter(row => !removed.has(row.id)); selected.clear();
      notice = 'CLEARED';
      return result;
    } catch (failure) {
      if (!disposed) {
        error = failure.message || 'Request failed';
        // A failed deletion response may follow a committed server change.
        // Do not retry it automatically or keep stale rows actionable.
        if (deleting) { available = false; notice = 'CLEAR_UNCONFIRMED'; }
      }
      return null;
    } finally {
      busy = false; emit();
      if (!disposed) timer = schedule(refresh, 5000);
    }
  }
  emit(); void refresh();
  return {
    refresh,
    setFilter(value) {
      if (disposed || busy || !['ALL','BACKUP','RESTORE'].includes(value)) return;
      filter = value; selected.clear(); emit();
    },
    select(id, checked) {
      if (disposed || busy || loading || !available || !entries.some(row => row.id === id && (filter === 'ALL' || row.kind === filter))) return;
      if (checked) selected.add(id); else selected.delete(id);
      error = ''; notice = ''; emit();
    },
    clear: ids => action(ids, true),
    download: ids => action(ids, false),
    dispose() { disposed = true; lifecycle.abort(); cancel(timer); selected.clear(); entries = []; },
  };
}
