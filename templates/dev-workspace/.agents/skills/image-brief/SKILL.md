---
name: image-brief
description: Interview one question at a time to lock an image brief, then generate with imagine. Use when drawing, illustrating, or the user is vague about a picture.
---

# Image brief

Lock the picture before generating. Prompt craft and tool choice live in `imagine`; See1 character files follow `character-art`. Do not restate those skills here.

## When to skip the interview

The brief is already locked (subject, style, framing, and whether a reference exists). Use the user's prompt verbatim if they gave one. Then go to `imagine`.

## Interview

Walk this tree depth-first. One question per turn. Each question names alternatives and carries a recommended answer plus one-sentence rationale.

1. Subject — who or what is in the frame
2. Style — medium and look
3. Framing — crop and aspect ratio
4. Reference — existing image to edit, or generate from text

If a later branch is already answered, skip it. If a decision depends on an earlier one, ask the earlier one first.

When every branch is locked, state the brief in four short lines (subject, style, framing, reference) and generate with `imagine`.
