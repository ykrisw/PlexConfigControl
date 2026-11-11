const panels = ['Dashboard', 'Backup', 'Restore', 'History', 'Settings'];
const paths = [
  '<rect x="3" y="3" width="6" height="6"/><rect x="15" y="3" width="6" height="6"/><rect x="3" y="15" width="6" height="6"/><rect x="15" y="15" width="6" height="6"/>',
  '<rect x="4" y="8" width="16" height="13" rx="2"/><path d="M3 3h18v5H3zM9 12h6"/>',
  '<path d="M3 10a9 9 0 1 1 1 8M3 3v7h7"/>',
  '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  '<path d="m9 3-1 3-3 1 1 4-2 2 2 3 3-1 3 2 3-2 3 1 2-3-2-2 1-4-3-1-1-3z"/><circle cx="12" cy="11" r="3"/>',
];

export function mountPanelShell(root, {onNavigate = () => {}, theme = 'System'} = {}) {
  const document = root.ownerDocument;
  const link = document.createElement('link');
  link.rel = 'stylesheet'; link.href = '/assets/panel-layout.css';
  root.replaceChildren(link);
  root.classList.add('pcc-shell');
  const header = document.createElement('header'); header.className = 'pcc-header';
  header.innerHTML = '<div class="pcc-brand"><svg class="pcc-logo" viewBox="0 0 24 28" aria-hidden="true"><path d="M12 2 3 6v7c0 6 4 10 9 13 5-3 9-7 9-13V6Z" fill="none" stroke="currentColor" stroke-width="3"/><path d="m7 13 3 3 7-7" fill="none" stroke="currentColor" stroke-width="3"/></svg>PlexConfigControl</div>';
  const nav = document.createElement('nav'); nav.className = 'pcc-nav';
  nav.setAttribute('role', 'tablist'); nav.setAttribute('aria-label', 'Main navigation');
  const main = document.createElement('main'); main.className = 'pcc-main';
  const sections = new Map(), buttons = new Map(), events = new AbortController();
  // Per-instance identifiers allow independent application previews/tests.
  const id = 'pcc-' + globalThis.crypto.randomUUID();
  for (const [index, title] of panels.entries()) {
    const key = title.toLowerCase();
    const button = document.createElement('button'); button.type = 'button';
    button.id = `${id}-${key}-tab`; button.setAttribute('role', 'tab');
    button.setAttribute('aria-controls', `${id}-${key}`);
    button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[index]}</svg><span>${title}</span>`;
    const section = document.createElement('section');
    section.id = `${id}-${key}`; section.className = 'pcc-page'; section.dataset.panel = key;
    section.setAttribute('role', 'tabpanel'); section.setAttribute('aria-labelledby', button.id);
    sections.set(key, section); buttons.set(key, button);
    button.addEventListener('click', () => select(key), {signal: events.signal});
    nav.append(button); main.append(section);
  }
  header.append(nav); root.append(header, main);
  function select(key) {
    if (!sections.has(key)) throw new Error('Unknown panel');
    root.dataset.activePanel = key;
    for (const [name, section] of sections) {
      section.hidden = name !== key;
      buttons.get(name).setAttribute('aria-selected', String(name === key));
    }
    onNavigate(key, sections.get(key));
  }
  function setTheme(value) {
    if (!['Light', 'Dark', 'System'].includes(value)) throw new Error('Unknown theme');
    root.dataset.theme = value.toLowerCase();
    for (const section of sections.values()) section.dataset.theme = value.toLowerCase();
  }
  setTheme(theme); select('dashboard');
  function setLanguage(language) {
    const names=language==='pl'?['Pulpit','Kopia zapasowa','Przywracanie','Historia','Ustawienia']:panels;
    for (const [index,title] of panels.entries()) buttons.get(title.toLowerCase()).querySelector('span').textContent=names[index];
  }
  return {sections, select, setTheme, setLanguage, dispose() {
    events.abort(); root.replaceChildren(); root.classList.remove('pcc-shell'); delete root.dataset.theme;
  }};
}
