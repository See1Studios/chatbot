---
name: anime-layer-animator
description: >
  Decomposes single 2D character illustrations into multi-layer PSD and transparent PNGs
  using See-Through AI (Gradio API), filters duplicated/misclassified layers, and generates
  real-time interactive 2.5D web motion viewers (eye tracking, full-occlusion blink,
  lip-sync, hair sway, tail wag, breathing) or packages assets for Stretchy Studio/Spine/Live2D.
---

# Anime Layer Animator (See-Through & 2.5D Interactive Rigging)

This skill automates the end-to-end pipeline of transforming a static 2D character illustration into layered, animatable components and interactive web/rigged motion.

## Workflow Overview

```text
[Static Illustration] (PNG/JPG)
         │
         ▼  (scripts/run_see_through.py via HuggingFace Space API)
[24+ Inpainted Layers & PSD]
         │
         ▼  (scripts/inspect_layers.py heuristic filter & pivot detection)
[Clean Filtered Layers & Exact Coordinates]
         │
         ├──► [Interactive 2.5D Web Viewer] (live.html: Eye-tracking, Blink, Lip-sync)
         └──► [Stretchy Studio / Spine / Live2D] (Auto-rigging with DWPose & Mesh Deform)
```

## Step 1: Remote Layer Decomposition (See-Through AI)

See-Through requires 12–16GB VRAM (NVIDIA CUDA). Running locally on low-VRAM or iGPU (e.g. AMD 780M / CPU) causes OOM or fails. Use the remote headless Gradio API runner:

```bash
python3 scripts/run_see_through.py /path/to/illustration.png -o output_dir/
```

- **Output:** `output_dir/<name>.psd` and individual transparent PNG layers (`00_backhair.png` ~ `23_wings.png`).
- Resolution recommended: `768` (fastest & fits ZeroGPU).

## Step 2: Layer Inspection & Heuristic Filtering (CRITICAL)

See-Through outputs raw semantic categories that frequently contain preview duplicates and misclassified fragments:

```bash
python3 scripts/inspect_layers.py output_dir/
```

### Known AI Traps & Exclusion Rules:
1. **The Ghost Head Duplicate (`12_head.png`):**
   - **Symptom:** Ghosting / 4 eyes / dual face.
   - **Cause:** `12_head.png` is often a flattened preview head containing eyes, mouth, and ears together.
   - **Fix:** **ALWAYS EXCLUDE `head`** when discrete parts (`face`, `eyewhite`, `irides`, `eyelash`, `mouth`, `ears`) exist! Use `08_face.png` (the blank inpainted skin) as the true head base.
2. **The Fake Nose Fragment (`19_nose.png`):**
   - **Symptom:** Strange dark spot or floating hair patch on forehead/nose.
   - **Cause:** See-Through misclassifies hair strands or forehead bangs as `nose`.
   - **Fix:** Check bounding box size. If larger than ~50px, exclude it.
3. **Double Tail / Backhair Merge (`00_backhair.png` vs `21_tail.png`):**
   - Inspect whether tail pieces leaked into backhair.

## Step 3: Layer Assembly & Stacking Order (Z-Index)

From back to front:
1. `23_wings.png` (Background / Accessories)
2. `21_tail.png` (Tail — low pivot)
3. `00_backhair.png` (Back hair)
4. `01_bottomwear.png`, `15_legwear.png`, `09_footwear.png`
5. `17_neck.png`
6. `22_topwear.png`, `18_neckwear.png`, `11_handwear.png`
7. **[Head Group]**:
   - `08_face.png` (Blank skin base)
   - `07_eyewhite.png` (Sclera)
   - `14_irides.png` (Pupil / Iris — target for mouse tracking)
   - `05_eyelash.png` (Upper & lower lashes / lids — target for blinking)
   - `04_eyebrow.png` (Brows)
   - `[mouth-cavity]` (Dynamic inner mouth background for speech)
   - `16_mouth.png` (Lips)
   - `02_ears.png`, `03_earwear.png` (Ears)
   - `10_fronthair.png` (Bangs / Front hair)
   - `06_eyewear.png`, `13_headwear.png`, `20_objects.png` (Props)

## Step 4: 2.5D Interactive Web Motion Rules

When building web viewers (e.g. `live.html`):

### 1. Pivot Coordinates Must Be Sampled from Actual Bbox
- Never guess `transform-origin` (e.g. 50% 50%).
- Run `scripts/inspect_layers.py` to extract exact center percentages:
  - Irides pivot: e.g. `(58.2%, 36.8%)`
  - Mouth pivot: e.g. `(58.7%, 41.0%)`

### 2. Full-Occlusion Eye Blinking Formula
- Merely scaling the eyelash (`scaleY`) leaves pupils staring through the lid.
- **Rule:** When blinking, fade out pupil + eyewhite (`opacity: 0` during 35%~65% of blink cycle) while moving eyelash down (`scaleY(0.1) translateY(3px)`).

### 3. Lip-Sync Cavity Formula
- Scaling a closed mouth line inflates the chin.
- **Rule:** Place a small radial-gradient pink oval (`#l-mouth-cavity`) behind the mouth line. During `talking`, open the cavity (`scale(1, 1.25)`) while slightly modulating lips (`scale(1.06, 0.82)`).

### 4. Subtle Ambient Motions
- Keep amplitude small (0.5° to 3.5°) so un-deformed flat layer seams do not separate:
  - Tail: ±3.5° wag
  - Hair: ±0.6° sway
  - Breathing: translateY(-1.5px) scale(1.002, 1.004)
  - Head tracking: ±2.5px max

## Step 5: Professional Mesh Rigging (Stretchy Studio / Spine)

For deformation without seam separation:
1. Open [https://stretchy.studio](https://stretchy.studio) (FOSS web tool).
2. Drag & drop the generated `<name>.psd`.
3. Run **Magic Auto-Rigging (DWPose)** to bind bones to layers automatically.
4. Export web animation runtime or sprite sheet.
