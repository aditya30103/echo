# Echo — Design System

> "Memory reconstructed by robotic agency."
>
> This phrase, found in a design session on 2026-05-18, is the north star.
> Every design decision is held against it. If it moves toward that image, it's right.
> If it moves away, it's wrong.

---

## What Echo Is

Echo is not a dashboard. It is not a data tool. It is not an analytics product.

Echo is the first place your digital self has been given a voice.

The feeling it should produce in the first 10 seconds: intimate, revealing, a little unsettling. Like hearing back from a version of yourself you didn't know existed. The name "Echo" is precise — your voice comes back to you, but from the outside, slightly distorted, more objective than you'd like.

**The governing metaphor:** A chest of drawers that had been hidden in a corner for years. You've just found it, opened it, and what's inside knows things about you.

---

## The Two Temperatures

This is the single most important principle in Echo's visual language. Every element belongs to one of two registers, and the seam between them IS the product.

### Warm amber — the human self

Memory. The physical drawer. The dust. The person who watched those videos, made those searches, lived those years. Represented by `--accent: #c2820a` and the **Lora serif** typeface.

Use warm amber for: things that were felt, intended, or remembered. The H1 wordmark. The session depth number. The Investigate button. The primary action. The preset prompts and textarea (invitations, not instructions).

### Cold mechanical signal — the reconstructed digital self

The agency that did the archaeology. The voice that isn't quite you. Represented by `--signal-cold: #7a9aaa` and the **Geist Mono** typeface.

Use cold signal for: source provenance chips, model labels, round indicators, phase banners, agent thoughts. Anything that says "the machine found this" rather than "you did this."

**Rule:** Never use `--signal-cold` for warm human data. Never use `--accent` for machine metadata. The temperatures must stay pure — mixing them collapses the tension that makes Echo feel the way it does.

---

## Color Tokens

All colors live in `:root` in `ui/src/app.html`. Never hardcode hex values in components — always reference tokens.

| Token | Value | Role |
|-------|-------|------|
| `--bg` | `#0c0906` | Page background — very dark warm char |
| `--surface-0` | `#140f0a` | Card backgrounds, deepest surface |
| `--surface-1` | `#1e1610` | Elevated surfaces, hover states |
| `--border` | `#2a1f15` | Borders, dividers |
| `--text-muted` | `#8a6a50` | Dim text, metadata, passive elements |
| `--text-secondary` | `#a89070` | Secondary text, labels |
| `--text-primary` | `#e8d5b0` | Primary body text — warm off-white |
| `--text-bright` | `#f5ead0` | High contrast text, headings, verdicts |
| `--accent` | `#c2820a` | Brand accent — deep amber (warm self) |
| `--accent-dim` | `#7a5008` | Dimmed accent, focus rings |
| `--accent-glow` | `#e8a020` | Hover/active state — warm gold |
| `--signal-cold` | `#7a9aaa` | Digital self — cold slate blue |
| `--signal-cold-dim` | `#3a5a6a` | Dimmed cold signal — source chip borders |
| `--data-green` | `#4a7c59` | Positive / correct |
| `--data-amber` | `#b07820` | Warning / medium confidence |
| `--data-red` | `#8a3a2a` | Error / wrong |

The dominant palette is warm brown-amber. `--signal-cold` is used sparingly and deliberately — only for elements that represent the digital self. This creates the two-temperature tension: open the drawer, and inside it is both warm and something slightly alien.

---

## Typography System

Two typefaces. No exceptions. This is the most visible expression of the two temperatures.

### Lora (serif) — the voice register

Used for everything synthesized, interpreted, narrated, or emotionally anchored:

- H1 "Echo" wordmark
- Subtitle: "Six years of watching. Who were you?"
- Echo Speaks query textarea (the invitation to ask)
- Preset prompts and suggestion buttons (literary invitations)
- Finding claims — the verdict Echo delivers
- Binge session depth number (the emotional number)

**Why Lora:** Warm, literary, authoritative, slightly old. Looks like it belongs in a well-made book. When the reconstructed self speaks, it speaks in Lora. The choice signals that this is interpretation, not measurement.

### Geist Mono (monospace) — the data register

Used for everything measured, categorized, timestamped, or mechanically derived:

- Body text, navigation tabs
- Section headings (H2)
- Percentages, counts, dates, timestamps
- Model names, round numbers, source tags
- Chapter identifiers and labels
- All interactive controls (buttons, selects, inputs)

**Why Geist Mono:** Clean, precise, terminal-adjacent. Everything the machine recorded appears in this face. The "robotic agency" signal — the fact that your data was measured and categorized is encoded in the type itself.

### Semantic CSS classes

Defined globally in `ui/src/app.html`:

```css
.voice-output {
  font-family: 'Lora', serif;
  font-size: 1rem;
  line-height: 1.7;
  color: var(--text-primary);
}

.data-output {
  font-family: 'Geist Mono', monospace;
  font-size: 0.875rem;
  line-height: 1.5;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
```

Apply these on new content areas. They make the register choice visible and auditable.

### Form element reset

Also in `ui/src/app.html`:

```css
button, input, select, textarea { font-family: inherit; }
```

This is required — browsers do not inherit `font-family` for form elements by default. Without it, all controls fall back to system-ui (Arial), which breaks the typographic system silently. Individual overrides (Lora on textareas and preset buttons) still apply correctly on top of this reset.

### Size scale

| Role | Size | Font |
|------|------|------|
| H1 "Echo" wordmark | 2.4rem | Lora 700, amber gradient |
| Section heading (H2) | 1.3rem | Geist Mono 600 |
| Body text | 1rem (16px) | Geist Mono 400 |
| Finding claim (the verdict) | 1rem | Lora 400 |
| Evidence / data backing | 0.75rem | Geist Mono 400 |
| Metadata / labels | 0.68–0.72rem | Geist Mono 400/600 |

---

## The H1 Wordmark

```css
h1 {
  font-family: 'Lora', serif;
  font-size: 2.4rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  background: linear-gradient(135deg, var(--accent), var(--accent-glow));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
```

The word "Echo" in warm amber-to-gold on near-black warm background is the entire visual proposition in one element. The gradient direction and token choices are intentional — do not change them.

---

## Component Patterns

### Source chips (`ui/src/lib/SourceChip.svelte`)

Source chips represent data provenance — where the machine found what it found. They are always cold signal. The `--signal-cold-dim` border on every source chip says: "this came from the digital record, not from your memory."

Used for: `[RAW-SQL]`, `[NARRATIVE]`, `[SEMANTIC-RAW]`, etc. in Echo Speaks findings and round observations.

Props: `label: string`, `color?: string` (defaults to `--text-secondary`).

```svelte
<SourceChip label="[RAW-SQL]" color="var(--data-green)" />
```

Do not render source provenance without this component. If you add a new place where source tags appear, use `SourceChip`.

### Session cards (`ui/src/lib/SessionCard.svelte`)

The binge session card has a deliberate hierarchy: the depth number (Lora 700, large) is the emotional anchor — it represents how deep you went, which is felt, not just counted. Everything else (dates, times, channel names) is mechanical record.

- Depth number: Lora 700, `--text-bright` — the emotional number
- Depth bar: `--accent` fill — your time, your investment
- Session metadata: Geist Mono (dates and times are records)
- Badges: encode intent (see Agency Map bar color semantics below)

### Agency Map bar colors

Bar colors in the Agency Map encode intent, not just value. The mapping has meaning and must be preserved:

| Signal | Color | Meaning |
|--------|-------|---------|
| Searched | `--signal-cold` | You sought it deliberately — cold precision, full agency |
| Bookmarked | `--accent` | You saved it consciously — warm, intentional |
| Autoplay | `--text-muted` | It happened to you — passive, dim |
| Rewatch | `--data-amber` | Nostalgia — warm amber, memory |

### Finding claim vs evidence

The visual structure encodes the reasoning chain:

```
Claim (Lora, --text-bright) ← backed by ← Evidence (Geist Mono, --text-secondary)
```

- Claim: Lora 400, `--text-bright` — the verdict in the voice register
- Evidence: Geist Mono 400, `--text-secondary` — the data behind it in the mechanical register
- Source chip: `--signal-cold-dim` border — provenance is always cold

Never render a claim and evidence in the same typeface. The seam between them is visible by design.

### Interactive controls

- **Primary action** (Investigate, Send): `--accent` background, `--bg` text, `--accent-glow` on hover. `min-height: 44px` always.
- **Secondary / ghost**: no background, `--border` border, `--text-muted` text. `min-height: 44px`.
- **Active nav tab**: `--accent` border and color — amber, not violet or any other color.
- **Model toggle (active)**: `--accent` text — the amber signal marks what's selected.
- **Advanced toggle**: ghost style, Geist Mono — it's a control, not an invitation.

### The void

The default state (no query run yet) is empty. This is intentional — not a bug, not an oversight. Do not add empty-state illustrations, decorative copy, or "get started" prompts. The card floating in a void communicates weight and seriousness. The emptiness IS the design.

---

## What Never Changes

These are permanent decisions, not conventions to reconsider:

1. **Violet/indigo is gone.** `#a78bfa`, `#4f46e5`, `#7c3aed` — none of these appear anywhere. The accent is amber, always.
2. **System-ui as a font is gone.** Every text element uses Lora or Geist Mono. The form element reset ensures controls inherit Geist Mono.
3. **`--signal-cold` is reserved for machine/provenance elements.** Never use it for warm human data.
4. **`--accent` is reserved for human/intentional data and primary actions.** Never use it for machine metadata.
5. **Touch targets are 44px minimum.** No exceptions on interactive elements.
6. **Hex values do not appear in components.** Only CSS token references.

---

## Adding New UI

Before writing a line of CSS for a new element, answer these four questions:

1. **Which temperature?** Is this warm (human, felt, intentional) or cold (machine, measured, mechanical)?
2. **Which register?** Does this belong in Lora (narrated, synthesized, voice) or Geist Mono (data, chrome, labels)?
3. **Which surface?** Card content → `--surface-0`. Elevated hover → `--surface-1`. Page background → `--bg`.
4. **Is it interactive?** If yes: `min-height: 44px`. Primary action → amber. Secondary → ghost.

If any answer is unclear, re-read "The Two Temperatures" above before proceeding.

---

## Origin

This design system emerged from a session on 2026-05-18. Before that session, Echo used system-ui fonts, Tailwind's violet/indigo color scheme, 14px body text, and 30px touch targets. The soul transplant replaced all of it across `ui/src/routes/+page.svelte`, `ui/src/lib/SpeakView.svelte`, and `ui/src/app.html`.

The phrase that governed the session: "memory reconstructed by robotic agency."

The metaphor that governed the design: a chest of drawers hidden in a corner for years — opened, and what's inside knows things about you.

These are not decorative framings. They are the specification.
