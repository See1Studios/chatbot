// Character Finder Portal & Wizard (cgs/F, #877). Step copy comes from GET /api/summon.
// Supports 3 creation modes: 7-step Create, SillyTavern Card Import, and Character Clone.
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
  if (!summonUi || summonUi.result || summonUi.mode !== 'create') return;
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
  if (old) {
    old.classList.remove('open');
    setTimeout(function () {
      if (old && old.parentNode) old.parentNode.removeChild(old);
    }, 280);
  }
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
    line.className = 'summon-summary-line';
    line.innerHTML = '<span class="summon-summary-lbl">' + escapeHtml(step.title) + ':</span> <span class="summon-summary-val">' + escapeHtml(value) + '</span>';
    box.appendChild(line);
  });
  var bond = summonSteps(spec).filter(function (s) { return s.id === 'bond'; })[0];
  if (bond && picks.user_title) {
    var title = document.createElement('div');
    title.className = 'summon-summary-line';
    title.innerHTML = '<span class="summon-summary-lbl">' + escapeHtml(bond.title_label || 'title') + ':</span> <span class="summon-summary-val">' + escapeHtml(picks.user_title) + '</span>';
    box.appendChild(title);
  }
  return box;
}

function renderDialoguePreview(example, charName, userTitle, portal) {
  var box = document.createElement('div');
  box.className = 'summon-dialog-box';
  var userSpk = (portal && portal.speaker_user) || 'User';
  var charSpk = (portal && portal.speaker_char) || 'Char';
  var lines = (example || '').split('\n');
  lines.forEach(function (line) {
    line = line.trim();
    if (!line) return;
    var row = document.createElement('div');
    if (line.indexOf('{{user}}') >= 0 || line.indexOf('{{user}}:') >= 0) {
      row.className = 'summon-bubble user';
      var text = line.replace(/\{\{user\}\}:?\s*/g, '');
      row.innerHTML = '<span class="summon-bubble-speaker">👤 ' + escapeHtml(userTitle || userSpk) + '</span>: <span>' + escapeHtml(text) + '</span>';
    } else {
      row.className = 'summon-bubble char';
      var text = line.replace(/\{\{char\}\}:?\s*/g, '');
      row.innerHTML = '<span class="summon-bubble-speaker">💬 ' + escapeHtml(charName || charSpk) + '</span>: <span>' + escapeHtml(text) + '</span>';
    }
    box.appendChild(row);
  });
  return box;
}

function paintCreateBody(step, body) {
  var picks = summonUi.picks;
  var spec = summonUi.spec;
  var portal = (spec && spec.portal) || {};

  if (step.kind === 'text') {
    var input = document.createElement('input');
    input.id = 'summonText';
    input.className = 'summon-text';
    input.type = 'text';
    input.placeholder = step.recommended ? (((portal.placeholder_rec || 'Recommended: ')) + step.recommended) : (portal.placeholder_input || 'Type here');
    input.value = picks[step.field] || '';
    body.appendChild(input);
  }

  if (step.kind === 'single' || step.kind === 'multi') {
    var grid = document.createElement('div');
    grid.className = 'summon-opts-grid';
    (step.options || []).forEach(function (opt) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'summon-opt-rich';
      var on = step.kind === 'multi'
        ? (picks.personality || []).indexOf(opt.id) >= 0
        : picks[step.field] === opt.id;
      if (on) btn.className += ' on';

      var label = document.createElement('span');
      label.className = 'summon-opt-label';
      label.textContent = opt.label;
      btn.appendChild(label);

      if (opt.card) {
        var cardDesc = document.createElement('span');
        cardDesc.className = 'summon-opt-card';
        cardDesc.textContent = opt.card;
        btn.appendChild(cardDesc);
      }

      btn.addEventListener('click', function () {
        readSummonStep();
        if (step.kind === 'multi') {
          var cur = (picks.personality || []).slice();
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
      grid.appendChild(btn);
    });
    body.appendChild(grid);

    var chosen = step.kind === 'single' ? summonOption(step, picks[step.field]) : null;
    if (chosen && chosen.example) {
      var previewBox = renderDialoguePreview(chosen.example, picks.name || 'Char', picks.user_title || 'User', portal);
      body.appendChild(previewBox);
    }
  }

  if (step.id === 'bond') {
    var label = document.createElement('label');
    label.className = 'summon-prompt';
    label.textContent = step.title_label || 'Title';
    body.appendChild(label);

    var chipsContainer = document.createElement('div');
    chipsContainer.className = 'summon-chips';
    var defaultChips = (portal.title_chips && portal.title_chips.length) ? portal.title_chips : [];
    defaultChips.forEach(function (chip) {
      var chipBtn = document.createElement('button');
      chipBtn.type = 'button';
      chipBtn.className = 'summon-chip';
      chipBtn.textContent = chip;
      chipBtn.addEventListener('click', function () {
        picks.user_title = chip;
        var input = document.getElementById('summonTitleInput');
        if (input) input.value = chip;
      });
      chipsContainer.appendChild(chipBtn);
    });
    body.appendChild(chipsContainer);

    var title = document.createElement('input');
    title.id = 'summonTitleInput';
    title.className = 'summon-text';
    title.type = 'text';
    title.placeholder = portal.placeholder_title || 'Type title here';
    title.value = picks.user_title || '';
    body.appendChild(title);
  }

  if (step.kind === 'confirm') body.appendChild(summonSummary(spec, picks));
}

function paintCreateActions(actions, step, steps) {
  var spec = summonUi.spec;
  var portal = (spec && spec.portal) || {};

  var back = document.createElement('button');
  back.type = 'button';
  back.className = 'art-filter-btn';
  back.textContent = summonUi.index > 0 ? (spec.back || 'Back') : (portal.back_to_modes || 'Modes');
  back.addEventListener('click', function () {
    readSummonStep();
    if (summonUi.index > 0) {
      summonUi.index -= 1;
      paintSummon();
    } else {
      summonUi.mode = 'select';
      paintSummon();
    }
  });
  actions.appendChild(back);

  if (summonUi.index < steps.length - 1) {
    var quickBtn = document.createElement('button');
    quickBtn.type = 'button';
    quickBtn.className = 'art-filter-btn';
    quickBtn.textContent = spec.summon_now || 'Quick';
    quickBtn.addEventListener('click', summonGo);
    actions.appendChild(quickBtn);
  }

  var next = document.createElement('button');
  next.type = 'button';
  next.className = 'primary';
  next.textContent = summonUi.index >= steps.length - 1 ? (spec.summon_now || 'Finish') : (spec.next || 'Next ➔');
  next.addEventListener('click', function () {
    readSummonStep();
    if (summonUi.index >= steps.length - 1) summonGo();
    else { summonUi.index += 1; paintSummon(); }
  });
  actions.appendChild(next);
}

function paintPortalModes(body) {
  var spec = summonUi.spec;
  var portal = (spec && spec.portal) || {};
  var container = document.createElement('div');
  container.className = 'summon-modes';

  // Mode 1: Create
  var card1 = document.createElement('div');
  card1.className = 'summon-mode-card';
  card1.innerHTML = '<div class="summon-mode-icon">✨</div>' +
    '<div class="summon-mode-head"><span class="summon-mode-title">' + escapeHtml(portal.mode_create_title || 'Create') + '</span>' +
    '<span class="summon-mode-tag">' + escapeHtml(portal.mode_create_tag || 'Custom') + '</span></div>' +
    '<div class="summon-mode-desc">' + escapeHtml(portal.mode_create_desc || 'Guided creation step by step.') + '</div>';
  var btn1 = document.createElement('button');
  btn1.type = 'button';
  btn1.className = 'primary';
  btn1.textContent = portal.btn_start || 'Start';
  btn1.addEventListener('click', function () {
    summonUi.mode = 'create';
    summonUi.index = 0;
    paintSummon();
  });
  card1.appendChild(btn1);
  container.appendChild(card1);

  // Mode 2: Import ST Card
  var card2 = document.createElement('div');
  card2.className = 'summon-mode-card';
  card2.innerHTML = '<div class="summon-mode-icon">📥</div>' +
    '<div class="summon-mode-head"><span class="summon-mode-title">' + escapeHtml(portal.mode_import_title || 'Import') + '</span>' +
    '<span class="summon-mode-tag">' + escapeHtml(portal.mode_import_tag || 'V2 Card') + '</span></div>' +
    '<div class="summon-mode-desc">' + escapeHtml(portal.mode_import_desc || 'Import SillyTavern character card (PNG).') + '</div>';
  var btn2 = document.createElement('button');
  btn2.type = 'button';
  btn2.className = 'art-filter-btn';
  btn2.textContent = portal.btn_select_file || 'Select File';
  btn2.addEventListener('click', function () {
    summonUi.mode = 'import';
    paintSummon();
  });
  card2.appendChild(btn2);
  container.appendChild(card2);

  // Mode 3: Clone Character
  var card3 = document.createElement('div');
  card3.className = 'summon-mode-card';
  card3.innerHTML = '<div class="summon-mode-icon">👥</div>' +
    '<div class="summon-mode-head"><span class="summon-mode-title">' + escapeHtml(portal.mode_clone_title || 'Clone') + '</span>' +
    '<span class="summon-mode-tag">' + escapeHtml(portal.mode_clone_tag || 'Variant') + '</span></div>' +
    '<div class="summon-mode-desc">' + escapeHtml(portal.mode_clone_desc || 'Clone an existing character into a new persona.') + '</div>';
  var btn3 = document.createElement('button');
  btn3.type = 'button';
  btn3.className = 'art-filter-btn';
  btn3.textContent = portal.btn_select_clone || 'Select';
  btn3.addEventListener('click', function () {
    summonUi.mode = 'clone';
    summonUi.cloneSelected = null;
    paintSummon();
  });
  card3.appendChild(btn3);
  container.appendChild(card3);

  body.appendChild(container);
}

function paintImportMode(body, actions) {
  var spec = summonUi.spec;
  var portal = (spec && spec.portal) || {};

  var drop = document.createElement('div');
  drop.className = 'summon-dropzone';
  drop.innerHTML = '<div class="summon-drop-icon">📂</div>' +
    '<div class="summon-drop-text">' + escapeHtml(portal.drop_prompt || 'Drop PNG card here or click to select') + '</div>' +
    '<input type="file" id="portalFileInput" accept=".png" style="display:none;" />';

  var fileInput = drop.querySelector('#portalFileInput');
  drop.addEventListener('click', function () { if (fileInput) fileInput.click(); });

  drop.addEventListener('dragover', function (e) {
    e.preventDefault();
    drop.classList.add('hover');
  });
  ['dragleave', 'dragend'].forEach(function (ev) {
    drop.addEventListener(ev, function () { drop.classList.remove('hover'); });
  });
  drop.addEventListener('drop', function (e) {
    e.preventDefault();
    drop.classList.remove('hover');
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
      handlePortalImportFile(e.dataTransfer.files[0]);
    }
  });
  if (fileInput) {
    fileInput.addEventListener('change', function () {
      if (fileInput.files && fileInput.files[0]) {
        handlePortalImportFile(fileInput.files[0]);
      }
    });
  }
  body.appendChild(drop);

  var back = document.createElement('button');
  back.type = 'button';
  back.className = 'art-filter-btn';
  back.textContent = portal.back_to_modes || 'Back';
  back.addEventListener('click', function () {
    summonUi.mode = 'select';
    paintSummon();
  });
  actions.appendChild(back);
}

function handlePortalImportFile(file) {
  if (!file || !summonUi) return;
  var portal = (summonUi.spec && summonUi.spec.portal) || {};
  summonUi.busy = true;
  summonUi.busyMsg = portal.importing_msg || 'Importing...';
  paintSummon();

  var formData = new FormData();
  formData.append('file', file, file.name || 'card.png');

  api('/api/characters/import', {
    method: 'POST',
    body: formData,
    headers: {},
    timeoutMs: 30000
  }).then(function (res) {
    if (!summonUi) return;
    summonUi.busy = false;
    if (res && (res.success || res.ok) && res.character) {
      summonUi.result = {
        ok: true,
        id: res.character.id,
        name: res.character.name,
        first_mes: portal.import_success || 'Card successfully imported!'
      };
    } else {
      summonUi.result = { ok: false, error: (res && res.error) || 'Import failed.' };
    }
    paintSummon();
  }).catch(function (err) {
    if (!summonUi) return;
    summonUi.busy = false;
    summonUi.result = { ok: false, error: String(err) };
    paintSummon();
  });
}

function paintCloneMode(body, actions) {
  var spec = summonUi.spec;
  var portal = (spec && spec.portal) || {};

  var catalog = (typeof characterCatalog !== 'undefined' && characterCatalog) ? characterCatalog : [];
  if (!catalog.length && typeof loadCharacters === 'function') {
    loadCharacters().then(function (list) {
      if (summonUi && summonUi.mode === 'clone') paintSummon();
    });
  }

  var prompt = document.createElement('p');
  prompt.className = 'summon-prompt';
  prompt.textContent = portal.clone_prompt || 'Select character to clone';
  body.appendChild(prompt);

  var grid = document.createElement('div');
  grid.className = 'summon-clone-grid';
  catalog.forEach(function (c) {
    var item = document.createElement('div');
    item.className = 'summon-clone-card' + (summonUi.cloneSelected && summonUi.cloneSelected.id === c.id ? ' on' : '');
    var avatar = document.createElement('img');
    avatar.className = 'summon-clone-avatar';
    avatar.src = c.avatar || ((typeof BASE_PATH !== 'undefined' ? BASE_PATH : '') + '/api/characters/' + encodeURIComponent(c.id) + '/avatar');
    avatar.alt = c.name;
    var name = document.createElement('span');
    name.className = 'summon-clone-name';
    name.textContent = c.name;
    item.appendChild(avatar);
    item.appendChild(name);
    item.addEventListener('click', function () {
      summonUi.cloneSelected = c;
      paintSummon();
    });
    grid.appendChild(item);
  });
  body.appendChild(grid);

  if (summonUi.cloneSelected) {
    var form = document.createElement('div');
    form.className = 'summon-clone-form';

    var nameLabel = document.createElement('label');
    nameLabel.className = 'summon-prompt';
    nameLabel.textContent = portal.clone_name_label || 'New Name';
    var nameInput = document.createElement('input');
    nameInput.id = 'cloneNameInput';
    nameInput.className = 'summon-text';
    nameInput.type = 'text';
    nameInput.value = summonUi.cloneSelected.name + ' (IF)';

    var titleLabel = document.createElement('label');
    titleLabel.className = 'summon-prompt';
    titleLabel.textContent = portal.clone_title_label || 'Title';
    var titleInput = document.createElement('input');
    titleInput.id = 'cloneTitleInput';
    titleInput.className = 'summon-text';
    titleInput.type = 'text';
    titleInput.placeholder = portal.placeholder_title || 'Title';

    form.appendChild(nameLabel);
    form.appendChild(nameInput);
    form.appendChild(titleLabel);
    form.appendChild(titleInput);
    body.appendChild(form);
  }

  var back = document.createElement('button');
  back.type = 'button';
  back.className = 'art-filter-btn';
  back.textContent = portal.back_to_modes || 'Back';
  back.addEventListener('click', function () {
    summonUi.mode = 'select';
    paintSummon();
  });
  actions.appendChild(back);

  if (summonUi.cloneSelected) {
    var submit = document.createElement('button');
    submit.type = 'button';
    submit.className = 'primary';
    submit.textContent = portal.clone_btn || 'Clone';
    submit.addEventListener('click', function () {
      var nameIn = document.getElementById('cloneNameInput');
      var titleIn = document.getElementById('cloneTitleInput');
      var newName = (nameIn && nameIn.value.trim()) || (summonUi.cloneSelected.name + ' (IF)');
      var newTitle = (titleIn && titleIn.value.trim()) || '';

      summonUi.busy = true;
      summonUi.busyMsg = portal.cloning_msg || 'Cloning...';
      paintSummon();

      api('/api/characters/' + summonUi.cloneSelected.id + '/clone', {
        method: 'POST',
        body: JSON.stringify({ name: newName, user_title: newTitle }),
        timeoutMs: 20000
      }).then(function (res) {
        if (!summonUi) return;
        summonUi.busy = false;
        if (res && res.ok && res.id) {
          summonUi.result = {
            ok: true,
            id: res.id,
            name: res.name || newName,
            first_mes: res.first_mes || (portal.clone_success || 'Character successfully cloned!')
          };
        } else {
          summonUi.result = { ok: false, error: (res && res.error) || 'Clone failed.' };
        }
        paintSummon();
      }).catch(function (err) {
        if (!summonUi) return;
        summonUi.busy = false;
        summonUi.result = { ok: false, error: String(err) };
        paintSummon();
      });
    });
    actions.appendChild(submit);
  }
}

function paintSummon() {
  if (!summonUi) return;
  var spec = summonUi.spec;
  var portal = (spec && spec.portal) || {};
  var root = document.getElementById('summonOverlay');
  if (!root) {
    root = document.createElement('div');
    root.id = 'summonOverlay';
    root.className = 'summon-overlay';
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    document.body.appendChild(root);
    requestAnimationFrame(function () { root.classList.add('open'); });
  }

  while (root.firstChild) root.removeChild(root.firstChild);

  var card = document.createElement('div');
  card.className = 'summon-card';

  // Head
  var head = document.createElement('div');
  head.className = 'summon-head';
  var headLeft = document.createElement('div');
  headLeft.className = 'summon-head-left';

  var headTitle = document.createElement('h2');
  headTitle.className = 'summon-head-title';
  headTitle.textContent = (spec && spec.menu) || portal.title || 'Find Character';

  var headSub = document.createElement('span');
  headSub.className = 'summon-head-sub';
  headSub.textContent = portal.subtitle || 'Select how to meet your character';

  headLeft.appendChild(headTitle);
  headLeft.appendChild(headSub);
  head.appendChild(headLeft);

  var closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'summon-close-btn';
  closeBtn.innerHTML = '✕';
  closeBtn.title = spec.close || 'Close';
  closeBtn.addEventListener('click', closeSummon);
  head.appendChild(closeBtn);

  card.appendChild(head);

  var scroll = document.createElement('div');
  scroll.className = 'summon-body-scroll';

  var actions = document.createElement('div');
  actions.className = 'summon-actions';

  card.appendChild(scroll);
  card.appendChild(actions);
  root.appendChild(card);

  // Busy State
  if (summonUi.busy) {
    var busy = document.createElement('div');
    busy.className = 'summon-busy';
    busy.innerHTML = '<div class="summon-weaver"></div><div class="summon-busy-msg">' +
      escapeHtml(summonUi.busyMsg || spec.waiting || 'Processing...') + '</div>';
    scroll.appendChild(busy);
    return;
  }

  // Result Arrival State
  if (summonUi.result) {
    var arrival = document.createElement('div');
    arrival.className = 'summon-arrival';
    if (summonUi.result.ok) {
      arrival.innerHTML = '<div class="summon-arrival-badge">' + escapeHtml(portal.badge_arrival || '✦ ARRIVED ✦') + '</div>' +
        '<h3 class="summon-title">' + escapeHtml(summonUi.result.name || spec.result_title || 'Ready') + '</h3>' +
        '<div class="summon-arrival-msg">' + escapeHtml(summonUi.result.first_mes || '') + '</div>';
    } else {
      arrival.innerHTML = '<div class="summon-arrival-badge err">' + escapeHtml(portal.badge_err || '✖ FAILED') + '</div>' +
        '<h3 class="summon-title">' + escapeHtml(spec.failed || 'Failed') + '</h3>' +
        '<div class="summon-arrival-msg">' + escapeHtml(summonUi.result.error || '') + '</div>';
    }
    scroll.appendChild(arrival);

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

  // Route modes
  if (summonUi.mode === 'select') {
    paintPortalModes(scroll);
  } else if (summonUi.mode === 'import') {
    paintImportMode(scroll, actions);
  } else if (summonUi.mode === 'clone') {
    paintCloneMode(scroll, actions);
  } else {
    // Mode: 'create'
    var steps = summonSteps(spec);
    var step = steps[summonUi.index] || {};

    // Segmented Track
    var track = document.createElement('div');
    track.className = 'summon-track';
    for (var i = 0; i < steps.length; i++) {
      var pip = document.createElement('div');
      pip.className = 'summon-track-pip' + (i < summonUi.index ? ' done' : (i === summonUi.index ? ' curr' : ''));
      track.appendChild(pip);
    }
    scroll.appendChild(track);

    var stepHeader = document.createElement('div');
    stepHeader.className = 'summon-step-header';
    stepHeader.innerHTML = '<span class="summon-step-num">STEP ' + (summonUi.index + 1) + '/' + steps.length + '</span> · <span class="summon-step-title">' + escapeHtml(step.title || '') + '</span>';
    scroll.appendChild(stepHeader);

    var prompt = document.createElement('p');
    prompt.className = 'summon-prompt';
    prompt.textContent = step.prompt || '';
    scroll.appendChild(prompt);

    paintCreateBody(step, scroll);
    paintCreateActions(actions, step, steps);
  }
}

function summonGo() {
  if (!summonUi || summonUi.busy) return;
  readSummonStep();
  summonUi.busy = true;
  summonUi.busyMsg = summonUi.spec.waiting || 'Processing...';
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
    summonUi = {
      spec: spec,
      mode: 'select',
      index: 0,
      picks: summonDefaults(spec),
      busy: false,
      busyMsg: '',
      result: null,
      cloneSelected: null
    };
    paintSummon();
  }).catch(function () {
    if (typeof showCharacterToast === 'function') showCharacterToast('Find Character');
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
