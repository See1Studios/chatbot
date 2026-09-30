// app-blocks.js -- what kind of text is this, and how should it be read (BLOCK_KINDS_v1, 2026-09-28).
//
// The model already answers in distinct kinds. private_engine.py::RENDER_PROTOCOL tells it to put
// actions and gaze in *italics*, speech in quotes, unexpressed thoughts in a ```thought fence, and
// the user's next move in a trailing choices comment. The client parsed three of those four
// (expression, thought, choices) and dropped the other two: a spoken line and an action both ended
// up as anonymous prose inside one .md blob. That is also why "the text is speech" had nowhere to
// show -- the spoken kind had no element of its own to be styled or moved.
//
// This file only says WHAT a piece of text is. It never decides how it looks or how it moves; that
// is chat-log.css and .impeccable/design.json, so a kind can be restyled without touching parsing.
//
// Conservative on purpose. Anything ambiguous stays narration: a wrong split damages the reading
// experience, while a missed split costs nothing but the treatment. Every ambiguous case is a
// test, not a hope.
//
// Declarations only -- this file loads before app.js, which runs everything at load.

const BLOCK_NARRATION = 'narration';
const BLOCK_DIALOGUE = 'dialogue';
const BLOCK_ACTION = 'action';

// Quotes this protocol actually emits: straight, curly, and the CJK brackets Korean replies use.
const QUOTE_PAIRS = { '"': '"', '\u201C': '\u201D', '\u300C': '\u300D', '\u300E': '\u300F' };
const QUOTE_OPENERS = Object.keys(QUOTE_PAIRS);
const _FENCE = /^\s*```/;

function isWholeWrapped(text, left, right) {
  const t = (text || '').trim();
  if (t.length < 2 || t[0] !== left || t[t.length - 1] !== right) return false;
  const inner = t.slice(1, -1);
  // A wrapper that has to close itself: no stray opener, and a non-empty inside.
  return inner.length > 0 && !inner.includes(left);
}

function fenceSpans(text) {
  // Split into alternating {fenced, code} runs so nothing inside a code fence is ever classified.
  // ```thought blocks are removed upstream (parseThought), so a fence here is a code block.
  const out = [];
  let rest = text || '';
  let guard = 0;
  while (guard++ < 200) {
    const open = rest.indexOf('```');
    if (open < 0) break;
    const close = rest.indexOf('```', open + 3);
    if (close < 0) { rest = rest.slice(0, open); break; }   // unterminated: treat the rest as code
    if (open > 0) out.push({ fenced: false, text: rest.slice(0, open) });
    out.push({ fenced: true, text: rest.slice(open, close + 3) });
    rest = rest.slice(close + 3);
  }
  if (rest) out.push({ fenced: false, text: rest });
  return out;
}

function countQuoteChars(text, opener) {
  let n = 0;
  for (let i = 0; i < text.length; i++) if (text[i] === opener) n++;
  return n;
}

function splitInline(text) {
  // Inside one block, separate narration from the action and the speech it contains. Returns runs
  // of {kind, text}. An unpaired quote anywhere means the block is left whole: guessing where a
  // sentence was meant to end is how a reply ends up with a stray quote mark in the middle of it.
  const src = text || '';
  const runs = [];
  let buf = '';
  // Whitespace that sits between two runs is dropped, not emitted as a run of its own and not
  // glued onto a neighbour: each run becomes its own element, so the gap between them is the
  // stylesheet's job, not a space character's.
  const push = (kind, t) => { runs.push({ kind: kind, text: t }); };
  const flush = () => {
    if (buf.trim()) push(BLOCK_NARRATION, buf);
    buf = '';
  };
  let i = 0;
  // Bold is consumed as a unit and everything inside it is left alone. `**a *b* c**` is bold with
  // an italic inside, and pulling the inner `*b*` out as an action of its own leaves two dangling
  // `**` in the prose -- louder damage than never classifying it. Same for a quote inside bold.
  let bold = 0;
  while (i < src.length) {
    const ch = src[i];
    if (ch === '*' && src[i + 1] === '*') { bold = 1 - bold; buf += '**'; i += 2; continue; }
    if (bold) { buf += ch; i++; continue; }
    // *action* -- a single-asterisk italic span only. `**bold**` was already taken above.
    // Left-flanking: no whitespace right after opening '*', and no whitespace right before closing '*'.
    if (ch === '*' && src[i + 1] && !/\s/.test(src[i + 1])) {
      const end = src.indexOf('*', i + 1);
      const inner = end > i + 1 ? src.slice(i + 1, end) : '';
      if (end > i + 1 && inner && !inner.includes('\n') && !inner.includes('*') && src[end - 1] !== '*' && !/\s/.test(src[end - 1])) {
        flush();
        push(BLOCK_ACTION, src.slice(i, end + 1));
        i = end + 1;
        continue;
      }
    }
    if (QUOTE_OPENERS.indexOf(ch) >= 0) {
      const closer = QUOTE_PAIRS[ch];
      const end = src.indexOf(closer, i + 1);
      if (end > i + 1) {
        const inner = src.slice(i + 1, end);
        // Balanced: the same opener must not appear again inside, and it must close on this line.
        if (inner && !inner.includes('\n') && countQuoteChars(inner, ch) === 0) {
          flush();
          push(BLOCK_DIALOGUE, src.slice(i, end + 1));
          i = end + 1;
          continue;
        }
      }
      // An opener with no partner on this line: the whole block is unclassifiable.
      return [{ kind: BLOCK_NARRATION, text: src }];
    }
    buf += ch;
    i++;
  }
  flush();
  if (!runs.length) return [{ kind: BLOCK_NARRATION, text: src }];
  return runs;
}

function classifyBlocks(text) {
  // Split a finished answer into the kinds it is made of, at paragraph level. Blank-line separated
  // paragraphs are the model's own unit, so this cannot cut a list apart or split a fence.
  const out = [];
  fenceSpans(text || '').forEach((part) => {
    // A fence keeps its own flag. It is already carved out of classification, but the renderer
    // splits a narration block inline -- and a quote inside code is a string literal, not speech.
    if (part.fenced) { out.push({ kind: BLOCK_NARRATION, text: part.text, fenced: true }); return; }
    part.text.split(/\n[ \t]*\n+/).forEach((para) => {
      if (!para.trim()) return;
      let kind = BLOCK_NARRATION;
      if (isWholeWrapped(para, '*', '*') || isWholeWrapped(para, '_', '_')) kind = BLOCK_ACTION;
      else if (QUOTE_OPENERS.some((q) => isWholeWrapped(para, q, QUOTE_PAIRS[q]))) kind = BLOCK_DIALOGUE;
      out.push({ kind: kind, text: para });
    });
  });
  return out.length ? out : [{ kind: BLOCK_NARRATION, text: text || '' }];
}

// STAGE_v1 (ux/S5, operator 2026-10-01): an action is not part of a bubble -- it is drawn as narration between
// bubbles. Which text counts is decided by shape alone, the same in every room: a paragraph that is one action
// (classifyBlocks already says so), or a paragraph made ONLY of actions and quoted speech, which is taken apart into
// its actions and its lines. Anything else stays whole: `this *really* matters` is emphasis, and `*smiling* fine.`
// mixes an action with unquoted prose, where the cut would be a guess.
// Which kinds are drawn outside the bubble is this one list (operator: keep it extensible). A new kind -- a move,
// a thought shown in the open -- joins by being classified above and named here; the grouping (app-messages.js
// stageLayout) and the layout (shell.css .md-narr) follow the list, and only the kind's own look is new CSS.
const STAGE_OUT = [BLOCK_ACTION];
function blockIsStaged(kind) { return STAGE_OUT.indexOf(kind) >= 0; }
function stageBlocks(blocks) {
  const out = [];
  (blocks || []).forEach((b) => {
    if (b.kind !== BLOCK_NARRATION || b.fenced) { out.push(b); return; }
    const runs = splitInline(b.text);
    const staged = runs.length > 1 && runs.some(r => blockIsStaged(r.kind)) && runs.every(r => r.kind !== BLOCK_NARRATION);
    if (!staged) { out.push(b); return; }
    runs.forEach(r => out.push({ kind: r.kind, text: r.text }));
  });
  return out;
}
// The blocks an answer is drawn as -- one function for the final render and the streaming reveal, so a block that
// closes while streaming already looks the way it will at the end.
function answerBlocks(text) { return stageBlocks(classifyBlocks(text)); }

function blockRuns(block) {
  // The runs a block renders as. Only prose is split inline, and a fenced block never is: it was
  // carved out of classification precisely because a quote in it is a string literal. Rendering is
  // the only consumer, and it used to inline-split a code block and turn print("hi") into speech.
  const b = block || {};
  if (b.kind === BLOCK_NARRATION && !b.fenced) return splitInline(b.text);
  return [{ kind: b.kind || BLOCK_NARRATION, text: b.text || '' }];
}

function blockIsQuiet(block) {
  // True when a block adds nothing on its own -- a continuation line of a list or a quote. Those
  // stay attached to the block above rather than becoming their own beat.
  const t = (block.text || '').trim();
  return !t || /^(?:[-*+]\s|\d+[.)]\s|>\s|\|)/.test(t);
}

// REVEAL_BLOCKS_v1 (2026-09-28): where a growing answer stops being finished.
//
// The complaint this answers is that a stream printed plain text and then turned into markdown at
// the end, so the end was a swap rather than an arrival. The fix is to render the real thing as it
// closes, which is only worth doing if "closed" is knowable. It is: a block of markdown has an
// extent, and once that extent has arrived the block can never change again. So a block is parsed
// ONCE, when it closes, and the per-frame work drops to the single block still being written.
//
// That is what makes this affordable. Re-parsing the whole document every frame measured 0.4ms at
// 164 characters and 1.8ms at 2440 -- fine, but it was solving a problem that a block boundary
// removes entirely. One parse per block, not one per frame.

var FENCE_OPEN = /^\s{0,3}(?:```|~~~)/;
var LIST_ITEM = /^\s*(?:[-*+]\s|\d+[.)]\s)/;
var TABLE_ROW = /^\s*\|/;
var HEADING = /^\s{0,3}#{1,6}\s/;
var LIST_CONTINUATION = /^\s{2,}\S/;

// The index just past the block starting at i, or -1 while that block is still being written.
function blockEnd(lines, i) {
  const first = lines[i] || '';
  if (!first.trim()) return i + 1;                       // a blank line closes on its own
  if (FENCE_OPEN.test(first)) {                           // code: until the closing fence
    for (let j = i + 1; j < lines.length; j++) if (FENCE_OPEN.test(lines[j])) return j + 1;
    return -1;
  }
  if (TABLE_ROW.test(first)) {                            // a table: until a line that is not a row
    let j = i + 1;
    while (j < lines.length && TABLE_ROW.test(lines[j])) j++;
    return j < lines.length ? j : -1;                    // still growing at the end
  }
  if (LIST_ITEM.test(first)) {                            // a list: until a blank or a non-item line
    let j = i + 1;
    while (j < lines.length && lines[j].trim()
           && (LIST_ITEM.test(lines[j]) || LIST_CONTINUATION.test(lines[j]))) j++;
    return j < lines.length ? j : -1;
  }
  if (HEADING.test(first)) return i + 1;                  // a heading is one line and always is
  for (let j = i + 1; j < lines.length; j++) {            // a paragraph: until the blank line
    if (!lines[j].trim()) return j;
  }
  return -1;                                              // no blank line yet
}

// The blocks of a growing answer that are finished, classified exactly as the final render will
// classify them, plus the one still being written. Both are needed: a block that just closed has to
// look the same as it will after `result`, or the final render is one more swap.
function revealBlocks(text) {
  const lines = String(text || '').split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const end = blockEnd(lines, i);
    if (end < 0) break;
    answerBlocks(lines.slice(i, end).join('\n')).forEach((b) => { if (b.text.trim()) out.push(b); });
    i = end;
    while (i < lines.length && !lines[i].trim()) i++;      // the gap between blocks is neither's
  }
  return { blocks: out, open: lines.slice(i).join('\n') };
}

// What kind is being written right now. The last thing with ink on it, not the dominant kind: a
// line that has an action and then speech is being spoken during, and the motion should say so.
function unitKind(text) {
  const runs = splitInline(String(text || ''));
  for (let i = runs.length - 1; i >= 0; i--) {
    if (runs[i].text.trim()) return runs[i].kind;
  }
  return BLOCK_NARRATION;
}
