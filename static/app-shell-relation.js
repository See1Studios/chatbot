// Profile: the relationship with this character as the engine reads it now (#875) -- a list of {label, value} lines
// from GET /api/characters/<id>/relationship (items.py FACT_SOURCES). The private session's data is still rough, so
// this only draws what comes: a new source on the server shows here with no change to this file. Split from
// app-shell.js (size cap); shellProfileOpen adds it when this file is loaded. Hidden until something arrives.

function shellRelationSection(c) {
  const box = shellSection(tr('profile.rel.title'));
  box.hidden = true;
  if (c && c.id) shellFillRelation(box, c.id);
  return box;
}

function shellRelationText(v) {   // a plain value, or a catalog line {key, vars}
  return v && typeof v === 'object' && v.key ? tr(v.key, v.vars || {}) : String(v === undefined || v === null ? '' : v);
}

async function shellFillRelation(box, cid) {
  try {
    const res = await api('/api/characters/' + encodeURIComponent(cid) + '/relationship');
    const facts = (res && res.facts) || [];
    if (!facts.length || !box.isConnected) return;
    const list = shellEl('div', 'status-list');
    facts.forEach(f => {
      const row = shellEl('div', 'status-item-head');
      row.append(shellEl('span', 'status-item-meta', shellRelationText(f.label)),
        shellEl('span', 'status-item-name', shellRelationText(f.value)));
      list.appendChild(row);
    });
    box.append(list, shellEl('div', 'status-hint', tr('profile.rel.hint')));
    box.hidden = false;
  } catch {
    /* the relationship is extra: the card stays as it was */
  }
}
