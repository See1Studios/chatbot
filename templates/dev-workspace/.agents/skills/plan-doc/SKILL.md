---
name: plan-doc
description: Write or update a plan document the way this repo's plans are written -- direction line, scope, current facts, decisions, item table, INDEX row.
---

# Plan document (plan)

## When to use
A proposal needs a plan before anyone builds it, or an existing plan needs new decisions or items.

## Before writing
- Read `docs/plans/INDEX.md`; extend an active plan instead of starting a duplicate.
- The standard is `docs/plans/plan-execution-workflow.md` §6 (required sections, item table) and §7 (Ready / Done). Follow
  it; do not restate it.

## Must have
- Under the title: `> 방향 (…): **등급** — 이유`, with the grade from INDEX.
- Current facts with date and how they were measured, kept apart from goals.
- Decisions as `D-n | question | recommendation | status`; items with runnable acceptance checks.
- The INDEX row in the same change. Code cited as `path` or `path::symbol`, never line numbers.

## Hand-off
A plan file in the repo is a code-side change: submit it as a `delegate` plan (or hand it to `dev`), and tell the
user which decisions are theirs.
