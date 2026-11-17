// One manual refresh updates every mounted archive view for this panel session.
const sessions = new WeakMap();
export function subscribeArchiveRefresh(client, refresh, signal) {
  let views = sessions.get(client);
  if (!views) sessions.set(client, views = new Set());
  views.add(refresh);
  const remove = () => { views.delete(refresh); if (!views.size) sessions.delete(client); };
  if (signal.aborted) remove();
  else signal.addEventListener('abort', remove, {once:true});
  return remove;
}
export function refreshArchiveViews(client) {
  return Promise.allSettled([...(sessions.get(client) || [])].map(refresh => Promise.resolve().then(refresh)));
}
