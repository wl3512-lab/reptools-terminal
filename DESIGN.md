# RepTools — DESIGN.md

Brand identity **v2: CARGO CULT** (streetwear maximalist), shipped June 2026. Replaces the
previous cyan/purple dark-tech system. Single source of truth lives in
[`static/css/brand.css`](static/css/brand.css), linked into every template before its inline
`<style>`. Each template deletes its own inline `:root` color tokens; brand.css supplies them
(plus back-compat aliases, so legacy `var(--accent-primary)` references map onto the new palette).

## The idea

RepTools sits where **streetwear drop culture meets logistics** (cop reps, track hauls from China,
scrape QC, clear customs). The identity fuses hype energy with cargo/customs/shipping language:
hazard orange, hard edges, oversized condensed type, tracking tickers, customs stamps, barcode
strips. Every device is true to what the product does, so it reads as intentional, not noise.
Name and domains are unchanged. Hero/H1 wording is unchanged.

## Register / two gears

- **LOUD** (homepage, contact, 404, empty states): full kit, ticker, stamps, oversized Anton.
- **WORK** (products, tools, order, measurements): identity via type + hazard accent + hard borders
  + mono labels; graphic noise dialed down so the tools stay fast and legible.

## Color — Full palette (OKLCH-intent, no pure #fff/#000)

| Token | Value | Use |
|---|---|---|
| `--ink` | `#0c0b0a` | Warm near-black, primary bg |
| `--ink-raised` | `#16130f` | Raised panels / cards |
| `--ink-line` | `#2a251d` | Borders on ink |
| `--bone` | `#f2ede1` | Warm paper/label, inverted surfaces, primary text |
| `--bone-dim` | `#b8b0a0` | Muted bone text |
| `--hazard` | `#ff4d00` | **Primary** — cargo/customs orange |
| `--hazard-deep` | `#d93d00` | Pressed / hover |
| `--acid` | `#d6ff3f` | Secondary pop, sparingly (≤5%) |
| `--stamp` | `#e5341e` | Customs-stamp red, graphic only |
| `--gl` / `--rl` / `--pending` | `#2fd167` / `#e5341e` / `#ffb020` | Status = rep slang (green light / red light / in transit) |
| `--on-hazard` | `#0c0b0a` | Near-black text on orange |

Back-compat aliases in brand.css: `--accent-primary→--hazard`, `--bg-primary→--ink`,
`--text-primary→--bone`, `--text-muted→#9a9182`, `--accent-success→--gl`, `--cy→--hazard`, etc.
Retired: all cyan (`#22d3ee`/`#00d4d4`/`#00d4ff`), purple (`#a855f7`/`#7b61ff`), and any glow.

## Typography

- **Display — `Anton`** — ultra-condensed poster caps. Hero, section heads, wordmark, big numbers,
  stamps. Uppercase, line-height ~0.9. Outline/stroke allowed (`-webkit-text-stroke`, solid).
- **Body/UI — `Archivo`** — grotesk with edge (deliberately not Inter).
- **Mono/data — `Space Mono`** — tracking numbers, tags, labels, ticker. Reads as shipping label.
- `--font-display`, `--font-body`, `--font-mono`; `--step-hero: clamp(3.25rem,11vw,8.5rem)`.

## Wordmark

`[REP]TOOLS` woven-tag lockup: `REP` on a skewed hazard tab (clothing-label feel) + `TOOLS` in
bone Anton, optional Space Mono microtag (`QC // TRACK // CONVERT`). Class `.cc-wordmark`. Favicon
is the orange REP tab on ink ([`static/favicon.svg`](static/favicon.svg)).

## Components (brand.css)

`.cc-wordmark`, `.cc-display` (+`--outline`), `.cc-btn` / `.cc-btn--ghost` (hard border + solid
offset shadow, hover translate), `.cc-box` (+`--hazard`), `.cc-tag` (+`--gl`/`--rl`/`--pending`),
`.cc-stamp` (rotated customs badge), `.cc-ticker` / `.cc-ticker__track` (marquee), `.cc-barcode`
(divider strip).

## Surfaces, motion, bans

- Cards/panels: hard 2px borders + **solid** offset shadows (`6px 6px 0`), radius 0–4px. Borders
  over blurred shadows.
- Motion: ease-out only (`cubic-bezier(0.22,1,0.36,1)`); ticker is linear-infinite; hover = snap
  translate / color-invert. Gated behind `prefers-reduced-motion`.
- **Banned** (enforced): gradient text, glassmorphism / `backdrop-filter` as decoration,
  `border-left/right` accent stripes, bounce/elastic easing, pure `#fff`/`#000`, em dashes in copy.

## Accessibility baseline (carried from the prior hardening pass)

Keyboard-operable real elements (no `div onclick`), visible hazard focus ring
(`:focus-visible{outline:3px solid var(--hazard)}` global in brand.css), labeled inputs,
`role="tablist/tab/tabpanel"`, dialog semantics + focus trap on modals, ≥44px touch targets,
`aria-hidden` on decorative emoji/SVG.

## Voice

Blunt, community-fluent, confident. Rep vocabulary used honestly (haul, batch, QC, GL/RL, W2C).
ALLCAPS display + lowercase body. No corporate filler, no fake hype, no em dashes.

## Owner-owned exceptions (do not change without asking)

- Hero/H1 wording stays "Your All-in-One Rep Toolkit" and existing slogans (visual styling only).
- The homepage "browsing now" counter and the home/products "VERIFIED" purchase toasts are
  intentionally retained despite being simulated; reskinned only, wording/behavior unchanged.
- KakoBuy `affcode=thelude` is the money and must never be touched; competitor affiliate codes
  stay stripped in the converter.

## Not yet rebranded

Admin templates (`admin_*.html`, `_admin_chrome.html`) are behind login (internal-only) and still
use the old cyan. Legacy `index.html` is unrendered (no route). Reskin later if desired.
