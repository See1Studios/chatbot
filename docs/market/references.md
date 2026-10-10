# Market references

> As of 2026-10-10. Sources to keep checking for Private Engine positioning. Facts only, each with its source; the
> judgement lives in [market-direction-review.md](../plans/market-direction-review.md). A weekly watch (Mondays 09:03
> KST, run by the operator's assistant outside this repo) checks the sources below and reports what changed.
> Update this file when a fact here changes; add the date next to it.

## 1. aicompanionguides.com (review site)

- Site: https://aicompanionguides.com/
- A solo blog by "Alex" that reviews AI companion apps. Updated about daily.
- Covers Kindroid, Character.AI, Replika, Nomi, SillyTavern, Grok, Animates, and desktop and offline companions.
- Scoring: conversation quality 40%, memory and continuity 25% (a fact mentioned on day 1 is checked on day 14),
  value 20%, features and customization 15%.
  Source: https://aicompanionguides.com/blog/best-ai-companion-apps-2026/
- Affiliate links are disclosed. Paid newsletter "Going Deeper", $7/month.
- No RSS feed (`/feed` returns 404). Monitor new posts through https://aicompanionguides.com/sitemap.xml (`lastmod`).
- No contact or app submission form. Reader suggestions pick which app gets tested next.
  Source: https://aicompanionguides.com/blog/my-paid-newsletter-announcement-going-deeper/
  This is the realistic path to get Private Engine reviewed: pitch it into their desktop and offline/local categories.
- They wrote that nobody ships portable relationships (no app lets you take the relationship with you).
- Useful articles:
  - Animates first look: https://aicompanionguides.com/blog/animates-app-first-look-2026/
  - Desktop companions: https://aicompanionguides.com/blog/desktop-ai-companion-best-options-beyond-mobile/
  - Offline companions: https://aicompanionguides.com/blog/best-offline-ai-companions-2026/
  - Grok Companions alternatives: https://aicompanionguides.com/blog/grok-companions-alternatives-2026/
  - How companion memory works: https://aicompanionguides.com/blog/how-ai-companion-memory-works-2026/
  - Pricing guide: https://aicompanionguides.com/blog/ai-companion-pricing-guide-2026/

## 2. Animates (Animation Inc.)

- Links: https://animates.ai/ , App Store https://apps.apple.com/us/app/animates-life-companions/id6758621319 ,
  Google Play https://play.google.com/store/apps/details?id=inc.animation.animate . Mac and Windows builds exist.
  X: @animates. A Discord server.
- Took over the xAI Grok Companions (Ani, Valentine, Mika, Rudi) after xAI shut Companions down (announced
  2026-09-01, fully off around 2026-09-07).
- Timeline (2026): Android and Windows Aug 17; iOS Aug 28; Ani Aug 29-30; Mika Sep 10; Valentine Oct 9 (iOS 1.1.4).
  Releases are roughly weekly.
- Pricing (US, as of 2026-09-20): free with a daily limit; Whisper $7.99/month, Heartbeat $19.99/month, Presence
  $39.99/month. Rated 18+. App Store 4.3 stars from about 2,000 ratings.
- Technology: on-device 3D animation (Ani-2) and Grok Voice. The model that writes replies is not confirmed. Memory is
  built in-house, kept per character, stored on their servers.
- Voice-first. Text chat is mostly through Telegram.
- Features: a diary the character writes about you; the character "keeps thinking" while the app is closed; screen
  sharing.
- Missing: users cannot create characters; personalities cannot be edited; no affection levels.
- Grok history, memory and affection did not migrate from Grok.
- Complaints:
  - Memory resets on paid plans: https://www.reddit.com/r/animates_ai/comments/1w217mm/animate_reset/
  - Memory leaking between characters: https://www.reddit.com/r/animates_ai/comments/1w0pgbg/possible_memory_leak_between_companions/
  - A short and inconsistent free limit.
  - "Not the same Ani" as on Grok.
- Fan tracker: https://companionsfan.cz/en/news/grok-end-sep7/ (feeds: `rss.php?lang=en`, `atom.xml` on that site).

## 3. Grok Bot used as a companion (X, October 2026)

- A minority of enthusiasts build lover bots in Grok Bot after Grok Companions ended. Most posts get tens to hundreds
  of views.
- Multi-bot setups with scheduled love notes, where one bot knows what the user showed another:
  https://x.com/MelanieCandra/status/2108179061248016790
- Two bots told to love each other: https://x.com/m0nle0z/status/2093666371284656637
- Complaints: memory does not carry over; characters removed by a company decision
  (https://x.com/Cerebro_FYI/status/2098168337603981558); censorship and roleplay refusal; the character drifts over
  time; usage limits run out; the app is designed for work only.
- The mass-appeal signal was cute character avatars, not romance: a Korean character-prompt post reached 8.33M views,
  https://x.com/Multi_Serio_Ai/status/2100800237619347535

## 4. What this means for Private Engine

- The gap is portable, local, per-character memory and relationship: the company cannot kill your character.
- BYOK and a one-time price avoid subscription tiers and usage meters.
- Card import and user-created characters, which Animates does not allow.
- A fixed character spec and consistent visuals answer the drift complaint.
- Worth copying: the character's diary, thinking between sessions, scheduled check-ins, multi-character rooms, image
  generation from the chat.
- Marketing leads with character customization, not romance. Public copy stays harness-first
  ([PRODUCT.md](../../PRODUCT.md)).
- Watch: the Animates Windows build, whether Animates adds user-created characters, and whether it adds MCP or tools.
