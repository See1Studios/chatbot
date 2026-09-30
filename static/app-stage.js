// app-stage.js -- how an answer with more than speech in it is laid out (STAGE_v1, docs/plans/ux-shell-roadmap.md
// ux/S5). Declarations only. It reads what app-blocks.js classified and app-messages.js built (`.md-block`s in the
// message's `.md`) and arranges it; the look is shell.css. Only under the messenger shell: the old page keeps the
// one-bubble answer.
//
// The order (operator, 2026-10-01): what the character DOES comes first, as narration in the middle of the log; then
// its FACE; then what it SAYS, as a bubble. Pressing the face opens what it THINKS beside it. Every answer of a
// character is laid out this way -- also one that is only speech (face, one bubble) and one still being written --
// so an answer looks the same from its first frame to its last; nothing is rearranged when the stream ends.
// A system notice is not a character speaking and keeps its plain bubble.
//
//   .md
//     .md-block.md-narr      an action, centred                 (any number, anywhere between the bubbles)
//     button.md-face         the character: before the first speech, or after the actions while nothing is said yet
//     .thought-box           (markdown.js makes it; moved here) hidden until the face is pressed
//     .md-say                a run of speech blocks = one bubble
//     .md-block.open         the block still being written (the streaming reveal inserts finished ones before it)

function stageOn() {
  const root = typeof document !== 'undefined' && document.documentElement;
  return !(root && root.classList) || root.classList.contains('shell2');
}
function stageHas(el, cls) { return Boolean(el && el.classList && el.classList.contains(cls)); }
function stageKids(md) { return Array.prototype.slice.call(md.children); }

// Runs on a body being built too (every frame of the streaming reveal), so it only wraps blocks that are not
// wrapped yet, never moves the block still being written, and moves the face only when its place changed.
function stageLayout(md) {
  if (!md || !md.children || !stageOn()) return;
  const msg = md.parentNode;
  if (stageHas(msg, 'system')) return;
  if (msg && msg.classList) msg.classList.add('staged');
  let kids = stageKids(md);
  const isBlock = (el) => stageHas(el, 'md-block') && !stageHas(el, 'open');
  kids.forEach((el) => {
    if (!isBlock(el)) return;
    if (blockIsStaged(el.getAttribute('data-kind'))) { el.classList.add('md-narr'); return; }
    if (!el.firstChild) return;               // nothing in it yet: no empty bubble
    let say = el.previousElementSibling;
    if (!stageHas(say, 'md-say')) {
      say = document.createElement('div');
      say.className = 'md-say';
      md.insertBefore(say, el);
    }
    say.appendChild(el);
  });
  kids = stageKids(md);
  const face = kids.find(el => stageHas(el, 'md-face')) || stageFace(md);
  // the first speech: a bubble, or the block being written unless what is being written is an action
  const first = kids.find(el => stageHas(el, 'md-say')
    || (stageHas(el, 'open') && !blockIsStaged(el.getAttribute('data-kind'))));
  if (first) {
    const i = kids.indexOf(first);
    const placed = kids[i - 1] === face || (stageHas(kids[i - 1], 'thought-box') && kids[i - 2] === face);
    if (!placed) md.insertBefore(face, first);
  } else if (kids[kids.length - 1] !== face) {
    md.appendChild(face);                     // nothing said yet: the face waits below what the character is doing
  }
  stageTyping(md, face);
  stageSync(md);
}

// While nothing of the answer is on screen yet, the face has the messenger's typing dots beside it (operator,
// 2026-10-01: waiting is "typing", not "writing" or "thinking" -- and needs no words). Shown only while the message
// is live (data-live, app-turn.js) and in the simple density (shell.css); the advanced one keeps its words.
function stageTyping(md, face) {
  const kids = stageKids(md);
  const shown = kids.some(el => stageHas(el, 'md-say') || stageHas(el, 'md-narr') || (stageHas(el, 'open') && el.firstChild));
  let dots = kids.find(el => stageHas(el, 'md-typing'));
  if (shown) { if (dots) md.removeChild(dots); return; }
  if (!dots) {
    dots = document.createElement('div');
    dots.className = 'md-typing';
    dots.setAttribute('aria-hidden', 'true');
    for (let k = 0; k < 3; k++) dots.appendChild(document.createElement('i'));
  }
  const after = kids[kids.indexOf(face) + 1];
  if (after !== dots) { if (after) md.insertBefore(dots, after); else md.appendChild(dots); }
}

// The face: the character's picture (--char-avatar, as the old corner picture) and the way to its thought.
function stageFace(md) {
  const face = document.createElement('button');
  face.className = 'md-face';
  face.type = 'button';
  face.addEventListener('click', () => {
    // in a group room the face calls the member: its @mention goes into the box (app-rooms.js)
    const who = md.parentNode && md.parentNode.dataset ? md.parentNode.dataset.roomWho : '';
    if (who && typeof roomMentionInsert === 'function') { roomMentionInsert(who); return; }
    const box = stageKids(md).find(el => stageHas(el, 'thought-box'));
    if (!box) return;
    box.hidden = !box.hidden;
    face.classList[box.hidden ? 'remove' : 'add']('open');
    face.setAttribute('aria-expanded', String(!box.hidden));
  });
  return face;
}

// After markdown.js has drawn the expression and the thought (postProcessAssistant calls this): the face takes the
// expression mark and the thought moves next to the face.
function stageSync(md) {
  if (!md || !md.children || !stageOn()) return;
  const msg = md.parentNode, kids = stageKids(md);
  const box = kids.find(el => stageHas(el, 'thought-box'));
  if (!stageHas(msg, 'staged')) { if (msg && !stageHas(msg, 'system')) stageLayout(md); return; }
  const face = kids.find(el => stageHas(el, 'md-face'));
  if (!face) return;
  const exp = msg && msg.getAttribute ? msg.getAttribute('data-exp') : null;
  if (exp) face.setAttribute('data-exp', exp);
  face.classList[box ? 'add' : 'remove']('has-thought');
  const toggle = kids.find(el => stageHas(el, 'thought-toggle'));
  if (toggle && toggle.title) { face.title = toggle.title; face.setAttribute('aria-label', toggle.title); }
  if (box) {
    const after = kids[kids.indexOf(face) + 1];
    if (after !== box) { if (after) md.insertBefore(box, after); else md.appendChild(box); }
  }
}
