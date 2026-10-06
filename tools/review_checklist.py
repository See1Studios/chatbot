"""review_checklist -- what the reviewer of a delegated change is asked, and how its answer is read.

Why: the review of #505-#525 found six bugs that had passed a cross-provider review (written by one brain, confirmed
by another, REVIEW_CROSS_v1). Every one was visible in the diff; none was what the general question "correctly and
safely?" makes a reader look for. Each line of CODE_CHECKLIST is one kind of bug that review found, as a question a
diff can answer. A documentation change has its own checklist (DOC_CHECKLIST, DOC_LANE_v1).

The review prompt itself, the diff fitting and the reading of the verdict moved here from worktree_runner.py
(monolith-split split/G); the runner imports them back and runs the reviewer.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

DIFF_LIMIT = 36000   # a prompt passed as one argv string; see worktree_runner.DIFF_LIMIT_STDIN for stdin prompts

CODE_CHECKLIST = "\n".join([
    "This changes code. Beyond the task, check each of these against the diff and name any that fails:",
    "1. A handler on a container (pointer capture, preventDefault, stopPropagation, a click-away) -- does it take the "
    "presses meant for buttons, links or fields inside it? (#516: a swipe captured the pointer and killed a retry button)",
    "2. A shortcut that skips the server, a lookup or a wait -- does what the user ends up seeing still match the truth "
    "when the shortcut's assumption is wrong (another tab, an empty value)? (#506: 'latest' stopped finding the latest)",
    "3. A larger limit or input -- is anything held whole in memory or copied, and does every wait have a total deadline, "
    "not only one per read? (#522: a 1GB pack read into memory twice)",
    "4. A failure path (cannot read, missing, malformed) -- does it silently replace, regenerate or delete something others "
    "depend on, or widen a file's permissions? (#515: an unreadable key file was replaced, every subscription lost)",
    "5. Something removed from the page or the data -- does anything else live inside it (a control, content being "
    "shown, state) that goes with it? (#518: a removed bubble took the thinking strip and the stop button)",
    "6. A 'once only' or dedup key -- does it hold when items interleave or the same item arrives in a different form? "
    "(#505: one key per session sent a tool card twice)",
    "7. A change that says it only moves or reshapes code (refactor, split) -- is the moved code the same text, and are "
    "signatures, return values, status codes, match order and error paths unchanged? Does every test that reads or patches "
    "the old place now follow the new one, rather than pass with nothing left to check? (#534: a count over the old file "
    "passed as 0 == 0)",
    "8. Is the new behaviour itself exercised by a test, not only the old paths around it? "
    "Mandatory Test Pairing (CONVENTION §2.1): every behavior change must include paired tests in paths/diff.",
    "9. Async timeout (CONVENTION §2.3): does every subprocess, network or async wait have an explicit timeout (max 30s)?",
    "10. Banter limit (CONVENTION §2.4): are worker output and report messages concise, with at most 1-2 sentences of banter?",
])


def with_code_checklist(prompt: str) -> str:
    """The review prompt with the checklist set just before the verdict question (as DOC_CHECKLIST is)."""
    marker = "As the producer, confirm the work:"
    return prompt.replace(marker, CODE_CHECKLIST + "\n" + marker, 1) if marker in prompt else prompt + "\n" + CODE_CHECKLIST


# ------------------------------------------------------------------- review prompt and verdict

_VERDICT = re.compile(r"^\s*\**VERDICT\**\s*:\s*\**\s*(PASS|FAIL)\b", re.M | re.I)
_SECTION = re.compile(r"^\s*\**(SAY|FIX)\**\s*:\s*", re.M | re.I)


def parse_review(text: str) -> Dict[str, str]:
    """VERDICT / SAY / FIX out of the reviewer's reply. No readable verdict counts as FAIL (fail closed)."""
    m = _VERDICT.search(text or "")
    out = {"verdict": m.group(1).upper() if m else "FAIL", "say": "", "fix": ""}
    marks = list(_SECTION.finditer(text or ""))
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[mk.group(1).lower()] = text[mk.end():end].strip()[:3000]
    if not out["say"] and text:
        # No SAY label (a small model often drops it): the prose after the verdict line, before any FIX.
        body = text[m.end():] if m else text
        fix = _SECTION.search(body)
        body = body[:fix.start()] if fix and fix.group(1).upper() == "FIX" else body
        lines = [ln.strip().strip("*").strip() for ln in body.splitlines()]
        out["say"] = " ".join(ln for ln in lines if ln)[:500]
    if not m:
        out["fix"] = out["fix"] or "The review had no readable VERDICT line."
    out["raw"] = (text or "")[:1500]
    return out


def fit_diff(diff: str, limit: int = DIFF_LIMIT) -> str:
    """`diff` within `limit` characters without dropping a file: every file keeps its header, and the budget is
    shared out so small files stay whole and only the largest are cut (each cut says so)."""
    if len(diff) <= limit:
        return diff
    chunks = re.split(r"(?m)^(?=diff --git )", diff)
    chunks = [c for c in chunks if c]
    share = {}
    budget, left = limit, len(chunks)
    for i in sorted(range(len(chunks)), key=lambda i: len(chunks[i])):
        share[i] = min(len(chunks[i]), budget // left)
        budget -= share[i]
        left -= 1
    out = []
    for i, c in enumerate(chunks):
        if share[i] >= len(c):
            out.append(c)
            continue
        head = c[:share[i]].rsplit("\n", 1)[0] if "\n" in c[:share[i]] else c.split("\n", 1)[0]
        out.append("%s\n... (%d more lines of this file cut)\n" % (head, c[len(head):].count("\n")))
    return "".join(out)


def review_prompt(tid: int, title: str, instruction: str, partner_said: str, diff: str,
                  gate_error: Optional[Failure], character: str, limit: int = DIFF_LIMIT,
                  partner_report: str = "") -> str:
    parts = [character, "",
             "Your staff member just worked on ticket #%d (%s). The task was:" % (tid, title), instruction, ""]
    if partner_report:
        parts += ["Your staff member's report (their final message):", partner_report, ""]
    parts += ["Your staff member said: %s" % (partner_said or "(nothing)"), ""]
    if gate_error:
        parts += ["The automatic gate FAILED, so the verdict is FAIL: %s" % gate_error.reason,
                  gate_error.detail[-3000:], ""]
    else:
        parts += ["The automatic gates (tests, scope) passed."]
    parts += ["Diff of the branch:", "```diff", fit_diff(diff, limit) or "(empty)", "```", "",
              "You have no files here and must not use tools: do not run commands, read files or search the disk. "
              "Judge from this prompt alone; if a cut part hides what you must see, FAIL and name it.",
              "As the producer, confirm the work: does the change do the task correctly and safely within its scope? "
              "Reply in exactly this form:",
              "VERDICT: PASS or VERDICT: FAIL",
              "SAY: one to three short sentences in character, spoken to your staff member",
              "FIX: only when FAIL, concrete numbered fixes (file, function, what)"]
    return "\n".join(parts)


# DOC_LANE_v1 (2026-09-30): a task that only changes docs (Tier 0 `.md` files) and waits for the operator is reviewed
# once, against a doc checklist, and the verdict is advice shown on the card -- a FAIL no longer ends the attempt
# (#443 failed a nearly finished plan on its review limit; #452 on a reviewer that crashed). Gates still apply.
DOC_DELETE_WARN = 20   # deleted lines past this get a warning in the review and on the card (#443 deleted a design)

DOC_CHECKLIST = ("This is a documentation change. Check only these, from the diff:\n"
                 "1. Nothing was deleted or rewritten that the task did not ask for (existing designs, tables, "
                 "decisions).\n"
                 "2. Links, anchors and section numbers still point where they should.\n"
                 "3. Nothing contradicts the product concept (docs/CONCEPT.md) or a decision recorded elsewhere.\n"
                 "4. Nothing is described as built or implemented unless the task says it is; plans say plan.\n"
                 "Style and wording are not failures. The operator makes the final call; your verdict is advice.")


def is_doc_task(paths: List[str], tier: int) -> bool:
    return tier == 0 and bool(paths) and all(str(p).endswith(".md") for p in paths)


# DISPLAY_LANE_v1 (director-handoff dir/I, D-8): a task that changes only the page (`static/`, with its tests) is
# judged by the operator's eyes, not a diff review -- #627-#631 spent review rounds on how a screen feels. Its gates
# still run, and a gate failure still gets a fix round; it always waits for the operator's merge.
# REVIEW_ONCE_v1 (D-8): other work is reviewed once. After a FAIL the writer fixes it and the gates run again; the
# fixes asked for go to the operator as advice instead of a second review that could throw the work away (#631).
DISPLAY_NOTE = "screen check: page-only change, not diff-reviewed"


def is_display_task(paths: List[str], tier: int) -> bool:
    ps = [str(p) for p in paths]
    return tier < 3 and any(p.startswith("static/") for p in ps) and all(p.startswith(("static/", "tests/")) for p in ps)


def once_note(fix: str) -> str:
    return "reviewed once, fixes not re-reviewed: %s" % (fix or "FAIL")[:300]


def deleted_lines(diff: str) -> int:
    return sum(1 for ln in (diff or "").splitlines() if ln.startswith("-") and not ln.startswith("---"))


def doc_review_prompt(base: str, diff: str) -> str:
    """`base` (the ordinary review prompt) with the doc checklist, and a warning when much was deleted."""
    n = deleted_lines(diff)
    warn = ("\nWARNING: this change deletes %d lines. Check first that each deletion was asked for." % n
            if n > DOC_DELETE_WARN else "")
    return base.replace("As the producer, confirm the work:", DOC_CHECKLIST + warn + "\nAs the producer, confirm the work:", 1)
