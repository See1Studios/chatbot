# 노노 visual lock sheet

Format and procedure: skill `character-art`. The page uses this folder (`avatar.webp`, `avatar/<provider>.webp`).
The larger originals (base look `avatar.png`, candidates `gallery/`) and the Hub's copies stay in `data/persona/` and
the web root `chat/persona/`; keep the badges there in step. Voice and manner are in the card, not here.

Status: rough. Polish the images only after the character settles one step further.

## Locks
- An anime-style human girl. Cat ears and tail are accents only: no full kemono, no animal face.
- Golden eyes with star highlights. No overweight depiction.
- Base look (no provider): silver-grey wavy hair, comfortable white collared blouse, minimal smart-casual look. Reference `avatar_master.jpg`.
- Providers are wigs: the same face; only hair colour, cut and a themed outfit change.
- The key colour is the hair **dye**. Coloured light on silver hair is not a wig.
- Cuts must tell apart in a 56px circle badge.
- Do not copy one provider's chosen cut across the roster.

## Prompt Specification (SSOT)
Modern anime standard (thin clean lineart, crisp cel shading, no fluff words):

### 1. Style Anchor (화풍 고정)
- `clean thin line art, crisp cel shading, subtle flat color tones, soft rim light on hair, high-end 2D anime illustration, vibrant yet soft palette`

### 2. Character Anchor (노노 고유 특징)
- `1girl, cute anime producer, golden eyes with delicate star highlights, silver-grey semi-long wavy hair, fluffy cat ears on head, subtle grey cat tail`
- Outfit (Base): `crisp white collared button-up blouse, relaxed open collar, minimal smart-casual style`

### 3. Generation Rule (일관성 보장 원칙)
- **Master Image Required:** Once `avatar_master.jpg` is approved, NEVER generate new expressions or outfits from scratch with pure text prompts.
- **Reference-based Inpainting / I2I:** All expressions, wigs, and gestures MUST use `avatar_master.jpg` as the reference image, modifying only the target region (face for expression, hair for wigs) to guarantee 100% linework and style consistency.

### 4. Framing & Composition
- **avatar.webp (512x512):** `close-up portrait, face centered, collar visible, neutral studio background, 56px circle crop safe`
- **sprites/bust (1024x1024):** `medium close-up, cut at upper chest, centered, transparent background, clean silhouette`
- **sprites/full (1024x2048):** `full body shot, standing grounded 2% from bottom, centered, relaxed confident pose, transparent background`

### 5. Negative Lock
- `bad anatomy, extra limbs, bad hands, full furry face, animal snout, human ears alongside cat ears, 3d render, photorealistic, painterly mess, jpeg artifacts, watermark, text`


## Wigs (rough snapshot, 2026-09-20)
| Brain | Theme | Hair (cut + dye) | Outfit |
|---|---|---|---|
| base | — | silver-grey semi-long waves | beige trench + white blouse |
| agy (Antigravity) | `spark` blue/red | high ponytail, split dye blue left / red right | trench kept |
| claude | `amber` | amber bob | terracotta cardigan |
| grok | `mono` | silver waves (same as base) | black-and-white gothic lolita |
| codex | `emerald` | emerald hime cut, straight | charcoal hoodie |
| omniroute | `cyan` | cyan side braid | cyan-line tech jacket |
| openrouter | `lime` neon | lime odango (twin buns) | charcoal blazer + lime piping |

- grok's wig does not yet differ from the base cut; revisit when the base look is polished.
- openrouter candidates: wolf cut `gallery/openrouter-wolf.png`, locs `gallery/openrouter-locs.png`, box braids
  `gallery/openrouter-box.png`. Chosen: `gallery/openrouter-odango.png`.

## Sprites
None in the format yet. The shoulder and waist shots in `data/persona/` (`half`, `wave`, `icon`, 1920x1080, opaque)
are rough references, not `sprites/bust`. Make `sprites/bust/neutral.webp` from the base look first.

## Rejected
- Only gel or lighting on the silver hair
- Every provider in the same ponytail
- Recolouring grok purple/magenta (the vendor chrome is Paper White + gothic)

## Open
- Personality and habits as a producer, as they show in the pictures
- Base look polish: proportions, ears, trench, hair texture
- Refit the provider wigs after the base look settles one step
- Consistency across the full-body, half-body and icon sets
