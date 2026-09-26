# 코코 visual lock sheet

Format and procedure: skill `character-art`. The page uses this folder (`avatar.webp`).
Voice and manner are in the card, not here.

Status: first master. Polish only after the operator approves this look.

## Locks
- An anime-style human girl. No animal ears, no tail, no kemono.
- Teal/cyan eyes. Slim illustrator frame, not petite-child, not mature-tall.
- Base look: ink-black bob with orange-dyed tips, white collared shirt, ink-stained apron, a small paintbrush hairpin. Reference `avatar_master.jpg`.
- Distinct from 노노 (silver waves, gold star eyes, cat ears, white blouse) and 리리 (dark ash-brown messy hair, violet eyes, bunny ears, oversized hoodie).

## Prompt Specification (SSOT)
Modern anime standard (thin clean lineart, crisp cel shading):

### 1. Style Anchor (화풍 고정)
- `clean thin line art, crisp cel shading, subtle flat color tones, soft studio key lighting, high-end 2D anime illustration`

### 2. Character Anchor (코코 고유 특징)
- `1girl, cute anime illustrator, human ears only, teal cyan eyes, ink-black short bob hair with bright orange dyed tips, small paintbrush hairpin, white collared shirt, ink-stained cream apron`
- Palette: Primary #1a1a1e (hair), Secondary #ff7a3a (tips), Accent #2ec4b6 (eyes)

### 3. Generation Rule (일관성 보장 원칙)
- **Master Image Required:** Once `avatar_master.jpg` is approved, NEVER generate new expressions or outfits from scratch with pure text prompts.
- **Reference-based Inpainting / I2I:** All expressions, wigs, and gestures MUST use `avatar_master.jpg` as the reference image, modifying only the target region.

### 4. Framing & Composition
- **avatar.webp (512x512):** `close-up portrait, face centered, collar and apron strap visible, brush hairpin in frame, neutral studio background, 56px circle crop safe`
- **sprites/bust (1024x1024):** `medium close-up, cut at shoulders, centered, transparent background`
- **sprites/full (1024x2048):** `full body shot, standing grounded 2% from bottom, centered, transparent background`

### 5. Negative Lock
- `cat ears, bunny ears, animal ears, tail, kemono, full furry face, silver hair, gold eyes, oversized hoodie, bad anatomy, bad hands, 3d render, photorealistic, watermark, text`

## Wigs (optional)
| Brain | Hair (cut + dye) | Outfit |
|---|---|---|

## Sprites (optional)
| Framing | Labels made | Notes |
|---|---|---|

## Rejected
- Doubled-name candidates other than 코코 (린, 아오, 세이, 스미)

## Open
- First master awaiting operator approval
