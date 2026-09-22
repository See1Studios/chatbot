---
id: 28
title: Provider portrait hair must change silhouette and pigment, not lighting
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: "chatbot family: chatbot-self-improve — instance-specific, no propagation"
area: provider portraits
date: 2026-09-20
session_context: agy Gemini Spark portrait; siljangnim rejected blue/red gels on silver hair
parked_until:
resolved: 2026-09-20
resolution: Regenerated agy as dyed twin tails (blue/red pigment + new silhouette), not colored lighting.
reference:
---

**Issue:** First agy Gemini pass kept the default wavy cut and painted blue/red gels on silver hair. At 56px it still read as 냥피디-with-a-filter. Siljangnim: hair style and hair color have to carry the provider, lighting does not.

**Suggested improvement:** When swapping a provider portrait, change the cut (silhouette that survives the circular 56px crop) and dye the hair as pigment. Do not grade the existing silver wave.

**Principle:** A provider badge is identified by hair cut + hair color at icon size. Colored lighting on the default wig is not a new look.
