---
name: character-art
description: Character image format (avatar, wigs, bust/full sprites, visual.md). Read before making images.
---

# Character art

Every character's images follow one format, so any image agent can make them and the app can show them.
Before drawing, read the character's `visual.md` (its visual lock sheet). It overrides your taste.

## Where files go

Next to the card, so they travel with it: `$CHATBOT_DATA/workspace/characters/<id>/`

| File | Size | What |
|---|---|---|
| `avatar.webp` | 512x512 | The base look. Full-bleed square (no inner circle on empty canvas). Face fills a 56px circle: eyes in the upper half, chin above the bottom third, species ears in frame. Bust and body go in sprites. Required. |
| `avatar/<provider>.webp` | 512x512 | Optional "wig" for one brain (`agy`, `claude`, `codex`, `grok`, `omniroute`, `openrouter`). Same face; only hair colour, cut and outfit change. Missing = the base look is used. |
| `stage.webp`, `stage/<provider>.webp` | 1024x1024 | Optional chat background, one per brain like the wigs (same face and wig as that brain's badge). Missing = the neutral studio background. |
| `sprites/bust/<label>.webp` | 1024x1024, transparent | Optional shoulder shot: shoulders cut by the bottom edge, top of the head about 8% from the top. |
| `sprites/full/<label>.webp` | 1024x2048, transparent | Optional full body: feet on a line 2% above the bottom edge, centred. |
| `visual.md` | text | The lock sheet. Required. |
| `references/` | any | Style references (often other artists' work): study only, never copy; git-ignored, never shipped. Optional. |

- Sprites are for a character-only view (desktop mode) where the character talks in speech bubbles. Within one
  framing every label uses the same canvas, anchor and scale, so swapping an expression never moves the body:
  make `neutral` first and derive the others from it by editing the face only. `neutral` is required once a
  framing exists. Sprites use the base look; per-brain wig sprites are not part of the format yet.
- Size caps for `.webp`: avatar 200 KB, stage 300 KB, bust 400 KB, full 800 KB. A `.png` master of the same name may sit beside
  a `.webp`.
- Sprite labels are SillyTavern's expression-sprite labels, so imported sprite packs fit:
  admiration, amusement, anger, annoyance, approval, caring, confusion, curiosity, desire, disappointment,
  disapproval, disgust, embarrassment, excitement, fear, gratitude, grief, joy, love, nervousness, neutral,
  optimism, pride, realization, relief, remorse, sadness, surprise. Start with neutral, joy, sadness,
  anger, surprise, embarrassment if you only make a few.
- Every character alike: the page shows only these files. `data/persona/` (and the web root `chat/persona/`) keeps
  older copies of one character's pictures for the Hub; replace those too when you replace that character's.

## Procedure

1. Read `visual.md`. No sheet yet: write one from the template below and show it to the operator before drawing.
2. Base look first (`avatar.webp`). Wigs and sprites come only after the base look is settled; a framing's
   `neutral` comes before its other labels.
3. Wigs and sprite expressions: edit the base image with the face locked (your image tool's edit mode), never a fresh
   generation. The key colour is dyed into the hair, not a coloured light on the base hair.
4. Check the base look and wigs as a 56px circle (the face must fill it; the cut and colour must tell the brains apart), and sprites by laying each
   label over `neutral` (the body must not move).
5. Write `.webp` (and the `.png` master if you have one), then run
   `python3 tools/check_character_art.py <id>` from `services/chatbot` until it says ok.
6. Update the wig table and the rejected list in `visual.md` in the same change.

Never replace an image the operator approved without asking; add candidates under `gallery/` in the character
folder instead.

## visual.md template

```markdown
# <name> visual lock sheet

## Locks
- Body type, species and accents (what must never change)
- Eyes, face, build limits
- Base look: hair, outfit (reference: avatar.webp)

## Prompt Specification (SSOT)
### 1. Style Anchor (화풍 고정)
- Style: Clean 2D anime digital illustration, crisp cel shading, subtle soft gradients
- Linework: Thin and defined clean lineart
- Lighting: Soft studio key lighting, neutral ambient light

### 2. Character Anchor (외형 불변)
- Face & Eyes: [눈 모양/색상, 동공 특징]
- Hair: [기본 머리색, 헤어스타일, 앞머리/잔머리]
- Features: [귀/꼬리/헤어핀 등 고유 특징]
- Palette: Primary #[HEX], Secondary #[HEX], Accent #[HEX]

### 3. Framing (구도 키워드)
- Avatar: full-bleed close-up, face fills the 56px circle, eyes upper half, chin above the bottom third
- Bust: medium close-up, cut at shoulders, transparent background
- Full: full body shot, feet grounded at bottom 2%, transparent background

### 4. Negative Lock
- bad anatomy, bad hands, blurry, text, watermark, photorealistic, 3d render

## Wigs (optional)
| Brain | Hair (cut + dye) | Outfit |
|---|---|---|

## Sprites (optional)
| Framing | Labels made | Notes |
|---|---|---|

## Rejected
- What was tried and turned down, and why

## Open
- What is still rough
```
