---
id: 10
title: Automated 2D illustration layer decomposition and 2.5D interactive rigging workflow
status: actioned
type: open-source
skill: [anime-layer-animator]
proposes_skill: []
siblings_checked: none
area: methodology / rigging / animation
date: 2026-09-16
session_context: Decomposing NyangPD illustration via See-Through AI and building interactive 2.5D web motion
resolved: 2026-09-16
resolution: Authored anime-layer-animator skill with API runner, layer inspection heuristics, and web 2.5D viewer templates
reference: /volume1/homes/me/services/chatbot-data/workspace/.agents/skills/anime-layer-animator
---

**Issue:** Running neural layer decomposition (See-Through) on consumer hardware without high VRAM GPUs causes OOM. Furthermore, raw AI semantic decomposition outputs contain flattened preview duplicates (e.g. `12_head.png` including eyes/mouth) and misclassified fragments (e.g. hair strands labeled as `nose`), causing severe visual ghosting and distortion when directly assembled into motion rigs. Finally, naive CSS scaling for blinking and speech results in unoccluded pupils and stretched chins.

**Suggested improvement:** Created a dedicated reusable skill `anime-layer-animator`:
1. Remote headless Gradio API automation (`scripts/run_see_through.py`) bypassing local GPU constraints.
2. Heuristic layer validator (`scripts/inspect_layers.py`) that detects and excludes preview duplicate heads and misclassified noses while calculating exact pixel-accurate pivot centers.
3. Proven web formulas for 2.5D motion: full-occlusion blink (fading pupils behind lids), dynamic mouth cavity for natural lip-sync, and subtle ambient motion dampening (under 3.5°).
4. Direct bridge to Stretchy Studio (DWPose auto-rigging) via the generated PSD.

**Principle:** AI-generated semantic layers require heuristic filtering of flattened preview duplicates and bounding-box-derived pivot centers before any 2D skeletal or parallax rigging can produce coherent animation.
