# 리리 visual lock sheet

Format and procedure: skill `character-art`. The page uses this folder (`avatar.webp`).
Voice and manner are in the card, not here.

Status: operator locked 2026-09-26, session image 4 (`gallery/lock-blonde-fox.jpg`). Picker crop locked to face-fill `avatar.webp` (master stays wider).

## Locks
- Cute anime fox kemonomimi woman (human face, fluffy fox ears, fox tail). No snout, no full kemono.
- Teal/cyan eyes. Adult frame. Hyper-voluptuous bust.
- Base look: long golden-blonde hair with a middle wave (not tight curls, not stick-straight), peach inner ears, cream/white open-collar blouse. Reference `avatar_master.jpg`.
- Distinct from 노노 (silver waves, gold star eyes, cat ears, white blouse) and 코코 (dark ash-brown messy hair, violet eyes, bunny ears, oversized hoodie).
- Avatar is a full-bleed front close-up: face and fox ears fill the 56px circle. Bust and body belong in sprites.

## Prompt Specification (SSOT)
Modern anime standard (thin clean lineart, crisp cel shading):

### 1. Style Anchor (화풍 고정)
- `clean thin line art, crisp cel shading, subtle flat color tones, soft studio key lighting, high-end 2D anime illustration`

### 2. Character Anchor (리리 고유 특징)
- `1girl, young adult anime fox-girl, fluffy fox ears on head, fox tail, human face, teal cyan eyes, long golden-blonde hair with soft waves, peach inner ears, cream white open-collar blouse, hyper-voluptuous bust`
- Palette: Primary #e8b84a (hair), Secondary #f3c4a0 (ears), Accent #2ec4b6 (eyes)

### 3. Generation Rule (일관성 보장 원칙)
- **Master Image Required:** Once `avatar_master.jpg` is approved, NEVER generate new expressions or outfits from scratch with pure text prompts.
- **Reference-based Inpainting / I2I:** All expressions, wigs, and gestures MUST use `avatar_master.jpg` as the reference image, modifying only the target region.

### 4. Framing & Composition
- **avatar.webp (512x512):** `full-bleed close-up, front-facing, face centered, fox ears in frame, eyes in the upper half, chin above the bottom third, 56px circle crop fills with the face`
- **sprites/bust (1024x1024):** `medium close-up, cut at shoulders, centered, transparent background`
- **sprites/full (1024x2048):** `full body shot, standing grounded 2% from bottom, centered, transparent background`

### 5. Negative Lock
- `cat ears, bunny ears, snout, full furry face, silver hair, gold eyes, oversized hoodie, ink-black bob, orange-dyed tips, paint-stained apron, paintbrush hairpin, shrine maiden, fox fire, bad anatomy, bad hands, 3d render, photorealistic, watermark, text`

## Wigs (optional)
| Brain | Hair (cut + dye) | Outfit |
|---|---|---|

## Stage (optional)
- `stage.webp` (1024x1024): Cozy illustrator atelier and workroom with sunlight, wooden easel, and tablet.

## Sprites (optional)
| Framing | Labels made | Notes |
|---|---|---|

## Rejected
- Human-only look, no kemonomimi (first master; too close in face/shirt to the house producer portrait)
- Artist-apron fox (ink-black bob, orange tips, paintbrush pin, cream apron) — operator: too generic, then too scary when pushed to Tamamo/Yae
- Doubled-name candidates other than 리리 (린, 아오, 세이, 스미)

## Open
