---
name: chatbot
description: Dark glass NAS night console — Pretendard, charcoal shell, seven accent dials.
colors:
  bg: "#0a0c0f"
  bg-card: "#14171d"
  bg-subtle: "#181c24"
  text: "#edefef"
  muted: "#9ba1a3"
  accent: "#d1fe17"
  accent2: "#ddfe51"
  accent-contrast: "#0b0d10"
  lime: "#d1fe17"
  amber: "#ff8a50"
  cyan: "#38bdf8"
  emerald: "#34d399"
  violet: "#a78bfa"
  mono: "#f4f4f5"
  spark: "#6ea8fe"
typography:
  display:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Noto Sans KR, system-ui, sans-serif"
    fontSize: "1.35rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  headline:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Noto Sans KR, system-ui, sans-serif"
    fontSize: "1.15rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  title:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Noto Sans KR, system-ui, sans-serif"
    fontSize: "1.02rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  body:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Noto Sans KR, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  label:
    fontFamily: "Pretendard, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Noto Sans KR, system-ui, sans-serif"
    fontSize: ".78rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.01em"
rounded:
  sm: "4px"
  md: "10px"
  lg: "12px"
  bubble: "14px"
  pill: "20px"
spacing:
  xs: "0.35rem"
  sm: "0.6rem"
  md: "1rem"
  lg: "1.25rem"
components:
  button-primary:
    backgroundColor: "linear-gradient(180deg, rgba(209,254,23,0.22) 0%, rgba(209,254,23,0.12) 100%)"
    textColor: "{colors.accent2}"
    rounded: "{rounded.md}"
    padding: ".45rem .7rem"
  button-primary-hover:
    backgroundColor: "linear-gradient(180deg, rgba(209,254,23,0.30) 0%, rgba(209,254,23,0.18) 100%)"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
  button-ghost:
    backgroundColor: "{colors.bg-card}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: ".45rem .7rem"
  input-composer:
    backgroundColor: "{colors.bg-card}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: ".5rem .75rem"
    height: "42px"
  bubble-user:
    backgroundColor: "linear-gradient(180deg, rgba(209,254,23,0.16) 0%, rgba(209,254,23,0.08) 100%)"
    textColor: "{colors.text}"
    rounded: "{rounded.bubble}"
    padding: ".7rem .85rem"
  bubble-assistant:
    backgroundColor: "rgba(20,23,30,0.82)"
    textColor: "{colors.text}"
    rounded: "{rounded.bubble}"
    padding: ".7rem .85rem"
  stage:
    backgroundColor: "{colors.bg-card}"
    rounded: "{rounded.lg}"
---

# Design System: chatbot

## Overview

**Creative North Star: "The Night Console"**

This is a NAS night console, not a chat-product landing page. The shell is charcoal glass: dark cards, an inset glint on raised chips, blur on menus and assistant bubbles. Accent is a lamp on the dashboard — rare, theme-swappable, never the wallpaper. 냥피디 lives here as the operator's PD (portrait, studio wash at 12% opacity), not as a theme-park skin.

Density is Operate-mode: scan the header, read the log, type in the composer. Personality sits in the lime (or current dial) lamp, the cat producer portrait, and the slightly lifted chips — not in extra chrome.

**Key Characteristics:**
- Charcoal glass shell (`#0a0c0f` / `#14171d`) with Pretendard
- Seven accent dials; default Sphere Lime (`#d1fe17`); Grok uses Paper White (`mono`); Antigravity uses Gemini Spark (`spark`)
- Inset glint + 10–14px rounds on raised chips; primary only gets the accent gradient
- Full-viewport column (`max-width: 960px`, `100dvh`), compact rewrite at `640px`
- Instant log snaps — no smooth scroll on `#log`

## Colors

Neutral charcoal is the room. Accent is the lamp. Switching `data-theme` changes the lamp, not the walls.

### Primary
- **Sphere Lime** (`#d1fe17` / `--accent` on default `lime`): focus rings, selected tabs, primary fills, user-bubble tint. Pair with **Lime Lift** (`#ddfe51` / `--accent2`) for labels that must stay readable on dark fills. Text on lime uses **Ink** (`#0b0d10` / `--accent-contrast`).

### Secondary
Omitted as a second brand color. The four other dials are the same *role* as Primary, not a secondary palette:
- **Studio Amber** (`#ff8a50`) — `data-theme="amber"`
- **Electric Cyan** (`#38bdf8`) — `data-theme="cyan"`
- **Cyber Mint** (`#34d399`) — `data-theme="emerald"`
- **Neon Violet** (`#a78bfa`) — `data-theme="violet"`
- **Paper White** (`#f4f4f5` / `#ffffff`) — `data-theme="mono"` (Grok: dark shell, white highlight)
- **Gemini Spark** (`#6ea8fe` / `#ff6b81`) — `data-theme="spark"` (Antigravity: blue lamp, red-pink twin)

### Neutral
- **Pit** (`#0a0c0f` / `--bg`): page and body
- **Panel** (`#14171d` / `--bg-card`): stage, buttons, inputs
- **Well** (`#181c24` / `--bg-subtle`): recessed strips
- **Signal** (`#edefef` / `--text`): body copy
- **Quiet** (`#9ba1a3` / `--muted`): captions, placeholders, Hub chip
- **Hairline** (`rgba(255,255,255,0.08)` / `--border`): default stroke; hover lifts to `0.18`

**The Accent Lamp Rule.** Accent occupies a small fraction of any screen: focus, selected, primary, user bubble tint. Do not flood backgrounds with `--accent`. Other dials change only the lamp. **Paper White (`mono`, Grok) also dims the room** (`--text` `#9a9a9a`, `--muted` `#5c5c5c`, `--bg` `#050505`) so white highlight is not the same color as body copy. **Gemini Spark (`spark`, Antigravity) cools the room to navy** and splits the lamp: `--accent` blue, `--accent2` red-pink.

**The Accent Dials Rule.** Brand is not one hue. New chrome must read through `--accent` / `--accent2` / `--accent-rgb`, never a hardcoded lime (except the `lime` theme's own token values).

## Typography

**Display Font:** Pretendard (system Korean/UI fallbacks)
**Body Font:** Pretendard (same stack)
**Label/Mono Font:** `ui-monospace, SFMono-Regular, Menlo, Consolas` — activity log, slash names, code

**Character:** One family for the console. Weight and size do the hierarchy; do not add a display serif or Hub's Noto as the chat face.

### Hierarchy
- **Display** (700, 1.35rem / 0.95rem at 640px, 1.15, -0.02em): header `h1` "냥피디" only
- **Headline** (600, 1.15–1.25rem, 1.3): markdown `h1`/`h2` inside assistant bubbles
- **Title** (600, 1.02rem, 1.3): markdown `h3`, uses `--accent2`
- **Body** (400, 16px on the composer, 1.6 in bubbles): chat copy and textarea (16px is the mobile zoom floor)
- **Label** (600, 0.78rem / 0.62rem on mobile caption): header `.sub`, uppercase menu headers at 0.72rem / 0.5px tracking

**The One Face Rule.** Pretendard for UI. Mono only for logs, code, slash identifiers.

## Layout

Single centered column: `.wrap` `max-width: 960px`, `padding: 1rem 1rem 1.25rem`, `gap: 0.6rem`, height `100dvh` (`--app-height`). Header shrinks; `.stage` flexes; composer stays bottom.

At `max-width: 640px`, padding/gap collapse to `0.35–0.45rem`, header becomes a nowrap brand+tools row, Hub text hides. Composer textarea min-height `38px` on mobile vs `42px` desktop.

`#log` snaps `scrollTop` instantly. Do not set `scroll-behavior: smooth` on the log — session switch and scrollback restore race it.

## Elevation & Depth

Hybrid: flat pit, then glass panels. Depth is tonal (panel vs pit) plus an inset **glint** (`inset 0 1px 0 rgba(255,255,255,0.08)`) on raised chips. Menus and assistant bubbles add `backdrop-filter: blur(8–24px)`. Accent glow is hover/focus only.

### Shadow Vocabulary
- **Glint** (`inset 0 1px 0 rgba(255,255,255,0.08)`): every raised chip and the stage
- **Chip rest** (`0 2px 8px` accent-soft or black 0.25): buttons, user bubble
- **Chip hover** (`0 4px 14px` accent-glow) plus `translateY(-1px)` on primary
- **Stage** (`0 8px 30px rgba(0,0,0,0.4)` + glint)
- **Glass menu** (`0 16px 36px rgba(0,0,0,0.65)` + hairline + glint)
- **Focus lamp** (`0 0 0 2px` accent-glow on textarea; `outline: 2px solid var(--accent)` on `:focus-visible`)

**The Glint Rule.** Raised surfaces get the inset highlight. Recessed wells (textarea inner shadow) do not.

## Shapes

Default radius is **12px** (`--radius`) on the stage and composer field. Buttons and selects are **10px**. Speech chips are **14px** with a 4px bite on the trailing corner (user: top-right family; assistant: bottom-left family). Theme swatches and avatars are circles. Pills (switch track) are **20px**.

Hairline borders, not heavy strokes. Primary is the exception: accent-border at rest, solid `--accent` on hover.

## Components

### Buttons
Slightly floating chips, not marketing CTAs.

- **Shape:** 10px (composer controls 12px, height 42px)
- **Primary:** accent gradient fill, `--accent2` label, glint + soft glow. Hover: brighter gradient, white label, `translateY(-1px)`. Active: drop the lift
- **Ghost / default:** `--bg-card` + hairline. Hover: `--border-hover`. `.on` / `.ghost.on`: accent-soft fill + accent2 text
- **Focus:** 2px accent outline, 2px offset, 4px radius
- **Disabled:** opacity 0.5, no transform

### Chips
- **Tabs:** ghost buttons; selected icon stroke is `--accent` with a 6px glow
- **Theme swatches:** 22px circles; active ring is accent glow
- **Slash badges:** 4px radius, cmd uses accent tokens, skill uses mint (`#34d399`) even when the dial is not emerald — that mint is a type label, not the theme

### Cards / Containers
- **Stage:** 12px, `--bg-card`, hairline, stage shadow, studio photo wash at 12% opacity behind the log
- **Overflow menu:** 14px, blur(24px), glass shadow, min-width 210px
- **Modal:** same glass family; confirm card 420px
- **Internal padding:** stage log `1rem`; menu `0.5rem`

### Inputs / Fields
- **Composer textarea:** 12px, 16px type, inset well shadow, min-height 42px (38px mobile)
- **Focus:** accent border + 2px accent-glow ring (no generic outline)
- **Placeholder:** `--muted` at 0.85 opacity
- **Selects:** same chip language as ghost buttons

### Navigation
- **Header:** brand (avatar + name + provider caption in `--accent2`) left; tabs + overflow right
- **Hub chip:** fixed top-left glass pill; static in the header on mobile
- **Active tab:** `.on` + accent icon. `role="tablist"` on the bar
- **Mobile:** nowrap header; tab labels may collapse — keep the icon

### Signature — Chat bubbles
User: accent-tinted gradient, accent-border, 14px/4px bite, right aligned. Assistant: 82% opaque panel, blur(8px), hairline, left aligned. System notices reuse the assistant bubble without copy/TTS chips.

### Signature — (retired) mascot overlay
The floating layered-PNG mascot was removed on 2026-09-19: its position was ambiguous and even when "hidden" it could intercept clicks. If an animated character is wanted again, it replaces the background image instead of floating over the UI; nothing may sit above the chat and swallow input. Assets (`live.html`, the layer PNGs) are kept.

## Do's and Don'ts

### Do:
- **Do** paint interactive chrome with `--accent` / `--accent2` / `--accent-rgb` so all five dials keep working.
- **Do** put glint on raised chips and keep the pit/`--bg` untouched.
- **Do** keep the composer at 16px and 42px tall (38px at 640px).
- **Do** snap `#log` instantly on session change and new messages.

### Don't:
- **Don't** treat Sphere Hub `sphere-theme.css` (Noto + orange) as this chat's type or accent.
- **Don't** hardcode `#d1fe17` on new UI except as the `lime` token itself.
- **Don't** add `scroll-behavior: smooth` on `#log`.
- **Don't** flood a screen with accent glow; the lamp is rare on purpose.
- **Don't** introduce a second UI font family for "personality."
