// Summon wizard (cgs/F). Step copy comes from GET /api/summon. Two doors, one flow:
// the team pane button and the character tray. No second card format.
var summonUi = null;

function summonSteps(spec) {
  return (spec && spec.steps) || [];
}

function summonDefaults(spec) {
  var picks = { idea: '', look: '', personality: [], voice: '', bond: '', name: '', user_title: '' };
  summonSteps(spec).forEach(function (step) {
    if (step.kind === 'single' && step.recommended) picks[step.field] = step.recommended;
    if (step.kind === 'multi' && step.recommended) picks[step.field] = step.recommended.slice();
    if (step.field === 'name') picks.name = step.recommended || '';
    if (step.id === 'bond') picks.user_title = step.title_recommended || '';
  });
  return picks;
}

function summonOption(step, id) {
  var opts = step.options || [];
  for (var i = 0; i < opts.length; i++) if (opts[i].id === id) return opts[i];
  return null;
}

function readSummonStep() {
  if (!summonUi || summonUi.result) return;
  var step = summonSteps(summonUi.spec)[summonUi.index];
  if (!step) return;
  if (step.kind === 'text') {
    var input = document.getElementById('summonText');
    if (input) summonUi.picks[step.field] = input.value;
  }
  if (step.id === 'bond') {
    var title = document.getElementById('summonTitleInput');
    if (title) summonUi.picks.user_title = title.value;
  }
}

function closeSummon() {
  var old = document.getElementById('summonOverlay');
  if (old && old.parentNode) old.parentNode.removeChild(old);
  summonUi = null;
}

function summonSummary(spec, picks) {
  var box = document.createElement('div');
  box.className = 'summon-summary';
  summonSteps(spec).forEach(function (step) {
    if (step.kind === 'confirm' || !step.field) return;
    var value = '';
    if (step.kind === 'text') value = picks[step.field] || '';
    if (step.kind === 'single') {
      var opt = summonOption(step, picks[step.field]);
      value = opt ? opt.label : '';
    }
    if (step.kind === 'multi') {
      value = (step.options || []).filter(function (o) {
        return (picks.personality || []).indexOf(o.id) >= 0;
      }).map(function (o) { return o.label; }).join(', ');
    }
    var line = document.createElement('div');
    line.textContent = step.title + ': ' + value;
    box.appendChild(line);
  });
  var bond = summonSteps(spec).filter(function (s) { return s.id === 'bond'; })[0];
  if (bond && picks.user_title) {
    var title = document.createElement('div');
    title.textContent = (bond.title_label || 'title') + ': ' + picks.user_title;
    box.appendChild(title);
  }
  return box;
}

function paintSummonBody(step, body) {
  var picks = summonUi.picks;
  if (step.kind === 'text') {
    var input = document.createElement('input');
    input.id = 'summonText';
    input.className = 'summon-text';
    input.type = 'text';
    input.value = picks[step.field] || '';
    body.appendChild(input);
  }
  if (step.kind === 'single' || step.kind === 'multi') {
    var row = document.createElement('div');
    row.className = 'summon-options';
    (step.options || []).forEach(function (opt) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'summon-opt';
      var on = step.kind === 'multi'
        ? (picks.personality || []).indexOf(opt.id) >= 0
        : picks[step.field] === opt.id;
      if (on) btn.className += ' on';
      btn.textContent = opt.label;
      btn.addEventListener('click', function () {
        readSummonStep();
        if (step.kind === 'multi') {
          var cur = picks.personality.slice();
          var at = cur.indexOf(opt.id);
          if (at >= 0) cur.splice(at, 1); else cur.push(opt.id);
          if (!cur.length && step.recommended) cur = step.recommended.slice();
          picks.personality = cur;
        } else {
          picks[step.field] = opt.id;
          if (step.id === 'bond' && opt.title && !picks.user_title) picks.user_title = opt.title;
        }
        paintSummon();
      });
      row.appendChild(btn);
    });
    body.appendChild(row);
    var chosen = step.kind === 'single' ? summonOption(step, picks[step.field]) : null;
    if (chosen && chosen.example) {
      var preview = document.createElement('pre');
      preview.className = 'summon-example';
      preview.textContent = chosen.example;
      body.appendChild(preview);
    }
  }
  if (step.id === 'bond') {
    var label = document.createElement('label');
    label.className = 'summon-prompt';
    label.textContent = step.title_label || '';
    var title = document.createElement('input');
    title.id = 'summonTitleInput';
    title.className = 'summon-text';
    title.type = 'text';
    title.value = picks.user_title || '';
    body.appendChild(label);
    body.appendChild(title);
  }
  if (step.kind === 'confirm') body.appendChild(summonSummary(summonUi.spec, picks));
}

function paintSummonActions(actions, step, steps) {
  var spec = summonUi.spec;
  if (summonUi.index > 0) {
    var back = document.createElement('button');
    back.type = 'button';
    back.className = 'art-filter-btn';
    back.textContent = spec.back || 'Back';
    back.addEventListener('click', function () { readSummonStep(); summonUi.index -= 1; paintSummon(); });
    actions.appendChild(back);
  }
  var now = document.createElement('button');
  now.type = 'button';
  now.className = 'art-filter-btn';
  now.textContent = spec.summon_now || 'Summon';
  now.addEventListener('click', summonGo);
  actions.appendChild(now);
  var next = document.createElement('button');
  next.type = 'button';
  next.className = 'primary';
  next.textContent = summonUi.index >= steps.length - 1 ? (spec.summon_now || 'Summon') : (spec.next || 'Next');
  next.addEventListener('click', function () {
    readSummonStep();
    if (summonUi.index >= steps.length - 1) summonGo();
    else { summonUi.index += 1; paintSummon(); }
  });
  actions.appendChild(next);
  if (step) return;
}

function paintSummon() {
  if (!summonUi) return;
  var spec = summonUi.spec;
  var root = document.getElementById('summonOverlay');
  if (!root) {
    root = document.createElement('div');
    root.id = 'summonOverlay';
    root.className = 'summon-overlay';
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    document.body.appendChild(root);
  }
  while (root.firstChild) root.removeChild(root.firstChild);
  var card = document.createElement('div');
  card.className = 'summon-card';
  var progress = document.createElement('div');
  progress.className = 'summon-progress';
  var title = document.createElement('h2');
  title.className = 'summon-title';
  var prompt = document.createElement('p');
  prompt.className = 'summon-prompt';
  var body = document.createElement('div');
  var actions = document.createElement('div');
  actions.className = 'summon-actions';
  card.appendChild(progress);
  card.appendChild(title);
  card.appendChild(prompt);
  card.appendChild(body);
  card.appendChild(actions);
  root.appendChild(card);
  if (summonUi.busy) {
    title.textContent = spec.waiting || '...';
    return;
  }
  if (summonUi.result) {
    progress.textContent = '';
    title.textContent = summonUi.result.ok ? (spec.result_title || '') : (spec.failed || 'failed');
    prompt.textContent = summonUi.result.ok ? (summonUi.result.first_mes || '') : '';
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'art-filter-btn';
    close.textContent = spec.close || 'Close';
    close.addEventListener('click', closeSummon);
    actions.appendChild(close);
    if (summonUi.result.ok && summonUi.result.id) {
      var open = document.createElement('button');
      open.type = 'button';
      open.className = 'primary';
      open.textContent = spec.open || 'Open';
      open.addEventListener('click', summonMeet);
      actions.appendChild(open);
    }
    return;
  }
  var steps = summonSteps(spec);
  var step = steps[summonUi.index] || {};
  progress.textContent = (summonUi.index + 1) + '/' + steps.length;
  title.textContent = step.title || '';
  prompt.textContent = step.prompt || '';
  paintSummonBody(step, body);
  paintSummonActions(actions, step, steps);
}

function summonGo() {
  if (!summonUi || summonUi.busy) return;
  readSummonStep();
  summonUi.busy = true;
  summonUi.result = null;
  paintSummon();
  var picks = summonUi.picks;
  api('/api/characters/summon', {
    method: 'POST',
    body: JSON.stringify({ choices: picks, profile: 'short' }),
    timeoutMs: 70000
  }).then(function (data) {
    if (!summonUi) return;
    summonUi.busy = false;
    summonUi.result = data || { ok: false };
    paintSummon();
  }).catch(function () {
    if (!summonUi) return;
    summonUi.busy = false;
    summonUi.result = { ok: false };
    paintSummon();
  });
}

function summonMeet() {
  var id = summonUi && summonUi.result && summonUi.result.id;
  closeSummon();
  var chain = (typeof loadCharacters === 'function') ? loadCharacters() : Promise.resolve();
  Promise.resolve(chain).then(function () {
    if (typeof renderCharacterTray === 'function') renderCharacterTray();
    var list = (typeof characterCatalog !== 'undefined' && characterCatalog) ? characterCatalog : [];
    var found = null;
    for (var i = 0; i < list.length; i++) if (list[i].id === id) found = list[i];
    if (found && typeof selectCharacter === 'function') selectCharacter(found);
  });
}

function openSummonWizard() {
  api('/api/summon', { timeoutMs: 8000 }).then(function (spec) {
    var menu = document.getElementById('summonOpenBtn');
    if (menu && spec && spec.menu) menu.textContent = spec.menu;
    summonUi = { spec: spec, index: 0, picks: summonDefaults(spec), busy: false, result: null };
    paintSummon();
  }).catch(function () {
    if (typeof showCharacterToast === 'function') showCharacterToast('Summon');
  });
}

function initSummonUi() {
  var btn = document.getElementById('summonOpenBtn');
  if (!btn || btn._summonBound) return;
  btn._summonBound = true;
  btn.addEventListener('click', function () { openSummonWizard(); });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initSummonUi);
else initSummonUi();
