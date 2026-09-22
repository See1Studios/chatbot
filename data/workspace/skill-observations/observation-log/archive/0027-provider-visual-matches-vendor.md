---
id: 27
title: Provider portrait and lamp should match the vendor, not a leftover palette
status: actioned
type: internal
skill:
  - chatbot-self-improve
proposes_skill: []
siblings_checked: "chatbot family: chatbot-self-improve — instance-specific, no propagation"
area: provider portraits / accent dials
date: 2026-09-20
session_context: Grok was violet + magenta 냥피디 recolor; siljangnim asked for dark+white gothic
parked_until:
resolved: 2026-09-20
resolution: Added mono (Paper White) dial, remapped grok theme, replaced grok portrait with B&W gothic bust.
reference:
---

**Issue:** Provider skins were 냥피디 recolors on leftover accent dials (Grok → violet/magenta). The vendor's actual chrome (Grok: charcoal + white highlight, gothic mono art) was not used.

**Suggested improvement:** When a provider has a distinct public visual language, map `PROVIDER_META.theme` and the portrait to that language instead of the next unused rainbow dial.

**Principle:** A provider portrait is a vendor badge, not a costume recolor of the persona.
