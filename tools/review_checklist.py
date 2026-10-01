"""review_checklist -- what the reviewer of a delegated CODE change is asked, beside "does it do the task".

Why: the review of #505-#525 found six bugs that had passed a cross-provider review (written by one brain, confirmed
by another, REVIEW_CROSS_v1). Every one was visible in the diff; none was what the general question "correctly and
safely?" makes a reader look for. Each line below is one kind of bug that review found, as a question a diff can
answer. A documentation change has its own checklist (DOC_CHECKLIST in worktree_runner.py).
"""

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
    "7. Is the new behaviour itself exercised by a test, not only the old paths around it?",
])


def with_code_checklist(prompt: str) -> str:
    """The review prompt with the checklist set just before the verdict question (as DOC_CHECKLIST is)."""
    marker = "As the producer, confirm the work:"
    return prompt.replace(marker, CODE_CHECKLIST + "\n" + marker, 1) if marker in prompt else prompt + "\n" + CODE_CHECKLIST
