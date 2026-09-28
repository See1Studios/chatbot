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
    if (ch === '*') {
      const end = src.indexOf('*', i + 1);
      const inner = end > i + 1 ? src.slice(i + 1, end) : '';
      if (end > i + 1 && inner && !inner.includes('\n') && !inner.includes('*') && src[end - 1] !== '*') {
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
