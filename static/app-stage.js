// app-stage.js -- how an answer with more than speech in it is laid out (STAGE_v1, docs/plans/ux-shell-roadmap.md
// ux/S5). Declarations only. It reads what app-blocks.js classified and app-messages.js built (`.md-block`s in the
// message's `.md`) and arranges it; the look is shell.css. Only under the messenger shell: the old page keeps the
// one-bubble answer.
//
// The order (operator, 2026-10-01): what the character DOES comes first, as narration in the middle of the log; then
// its FACE; then what it SAYS, as a bubble. Pressing the face unfolds what it THINKS, between the face and the
// speech. So an answer is laid out this way when it has a block drawn outside the bubble (blockIsStaged: actions
// today) or a thought; an answer that is only speech stays the one bubble it was.
//
//   .md
//     .md-block.md-narr      an action, centred                 (any number, anywhere between the bubbles)
//     button.md-face         the character, before the first speech
//     .thought-box           (markdown.js makes it; moved here) hidden until the face is pressed
//     .md-say                a run of speech blocks = one bubble
//     .md-block.open         the block still being written (the streaming reveal inserts finished ones before it)

function stageOn() {
  const root = typeof document !== 'undefined' && document.documentElement;
  return !(root && root.classList) || root.classList.contains('shell2');
}
function stageHas(el, cls) { return Boolean(el && el.classList && el.classList.contains(cls)); }
function stageKids(md) { return Array.prototype.slice.call(md.children); }

// Runs on a body being built too (the streaming reveal), so it only wraps blocks that are not wrapped yet and never
// moves the block still being written. `force`: lay out even without a staged block (the answer has a thought).
function stageLayout(md, force) {
  if (!md || !md.children || !stageOn()) return;
  let kids = stageKids(md);
  const isBlock = (el) => stageHas(el, 'md-block') && !stageHas(el, 'open');
  const out = (el) => isBlock(el) && blockIsStaged(el.getAttribute('data-kind'));
  const msg = md.parentNode;
  if (!force && !kids.some(out) && !stageHas(msg, 'staged')) return;
  if (msg && msg.classList) msg.classList.add('staged');
  kids.forEach((el) => {
    if (!isBlock(el)) return;
    if (out(el)) { el.classList.add('md-narr'); return; }
    let say = el.previousElementSibling;
    if (!stageHas(say, 'md-say')) {
      say = document.createElement('div');
      say.className = 'md-say';
      md.insertBefore(say, el);
    }
    say.appendChild(el);
  });
  // the face goes before the first speech: a bubble, or the block being written unless that is an action so far
  kids = stageKids(md);
  let face = kids.find(el => stageHas(el, 'md-face'));
  const first = kids.find(el => stageHas(el, 'md-say')
    || (stageHas(el, 'open') && !blockIsStaged(el.getAttribute('data-kind'))));
  if (!first) {
    if (face) md.removeChild(face);      // nothing said yet: the actions stand alone
  } else {
    if (!face) face = stageFace(md);
    if (kids[kids.indexOf(first) - 1] !== face && !(stageHas(kids[kids.indexOf(first) - 1], 'thought-box') && kids[kids.indexOf(first) - 2] === face)) {
      md.insertBefore(face, first);
    }
  }
  stageSync(md);
}

// The face: the character's picture (--char-avatar, as the old corner picture) and the way to its thought.
function stageFace(md) {
  const face = document.createElement('button');
  face.className = 'md-face';
  face.type = 'button';
  face.addEventListener('click', () => {
    const box = stageKids(md).find(el => stageHas(el, 'thought-box'));
    if (!box) return;
    box.hidden = !box.hidden;
    face.classList[box.hidden ? 'remove' : 'add']('open');
    face.setAttribute('aria-expanded', String(!box.hidden));
  });
  return face;
}

// After markdown.js has drawn the expression and the thought (postProcessAssistant calls this): the face takes the
// expression mark, the thought moves under the face, and an answer that has a thought but no action is laid out too.
function stageSync(md) {
  if (!md || !md.children || !stageOn()) return;
  const msg = md.parentNode, kids = stageKids(md);
  const box = kids.find(el => stageHas(el, 'thought-box'));
  if (box && !stageHas(msg, 'staged')) { stageLayout(md, true); return; }
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
