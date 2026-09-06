# Vitta — Build Brief v4 (Aurora Borealis theme, dark)

Build a production-grade expense analytics web app for the Indian market. **Visual signature: real aurora borealis** — flowing curtains of green, cyan, blue, and violet light drifting across a deep navy canvas, with a subtle starfield behind. Not flat blobs — actual curtain-shaped bands that morph and drift slowly, like the real northern lights.

Reference: aurora borealis landing pages (mountain silhouette + navy sky + green/cyan/violet bands). Vitta's take strips the mountains and lands the aurora directly behind the product content.

**Read this whole document first, then start with Step 1.** Don't reproduce it back — build it.

---

## 0. Non-negotiables

- **Deep navy canvas**, not pure black. Aurora needs the navy to read correctly.
- **Aurora curtains** — SVG paths that morph and drift, layered green → cyan → violet. NOT static gradient blobs. See section 3.2.
- **Subtle starfield** behind the aurora, twinkling.
- **Lato only** for typography (the Slack face).
- **Framer Motion** for every animation.
- **Dark theme primary.** Light theme secondary.
- **LLM never does arithmetic** — LLM writes SQL, backend runs it, LLM narrates.

---

## 1. Product

**Vitta** (Sanskrit: वित्त — wealth, finance). Tagline: **"Every rupee, understood."**

Vitta ingests statements from any Indian bank, GPay, PhonePe, and credit cards. Parses them, deduplicates across sources, categorizes with a 3-tier engine (rules → user dictionary → LLM), and gives users a complete AI-narrated view of their spending.

Two audiences: personal users (self-serve) and small-business / freelancers / enterprise ("Talk to Sales" path).

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Frontend | Vite + React 18 + TypeScript |
| Styling | Tailwind CSS 4 with CSS custom properties |
| Animation | **Framer Motion** — every animation |
| Icons | Lucide React |
| Charts | Recharts + hand-rolled SVG for custom |
| Router | React Router v6 |
| State | Zustand (client) + TanStack Query (server) |
| Backend | Python FastAPI (separate service, `/backend`) |
| Database | Supabase (Postgres + Auth + Storage) |
| PDF parsing | pdfplumber, pypdf, camelot-py |
| LLM | Groq `llama-3.3-70b-versatile` (free) + Gemini 1.5 Flash fallback |
| Deployment | Vercel + Railway + Supabase |

---

## 3. Design system

### 3.1 Color — Deep navy canvas + aurora accents

```css
:root[data-theme="dark"] {
  /* Grounds — deep navy, not pure black */
  --bg:              #050B1F;                    /* deepest ground */
  --bg-elevated:     #0A1128;                    /* cards, elevated surfaces */
  --bg-glass:        rgba(255,255,255,0.03);     /* glass card on landing */
  --bg-glass-strong: rgba(255,255,255,0.06);
  --bg-inset:        rgba(255,255,255,0.02);

  /* Borders — hairlines of white */
  --border:          rgba(255,255,255,0.08);
  --border-strong:   rgba(255,255,255,0.16);
  --border-emphasis: rgba(255,255,255,0.28);

  /* Ink */
  --ink:             #FFFFFF;
  --ink-secondary:   rgba(255,255,255,0.75);
  --ink-muted:       rgba(255,255,255,0.52);
  --ink-faint:       rgba(255,255,255,0.30);

  /* Aurora palette — used for the curtains AND data-viz slot 1-5 */
  --aurora-green:    #4ADE80;
  --aurora-mint:     #6EE7B7;
  --aurora-cyan:     #22D3EE;
  --aurora-blue:     #60A5FA;
  --aurora-indigo:   #818CF8;
  --aurora-violet:   #A78BFA;
  --aurora-pink:     #E879F9;

  /* Brand — emerald green (aurora's most iconic color, doubles as growth signal) */
  --brand:           #4ADE80;
  --brand-bright:    #86EFAC;
  --brand-dim:       #22C55E;
  --brand-wash:      rgba(74,222,128,0.10);
  --brand-glow:      rgba(74,222,128,0.35);

  /* Semantic (kept off the aurora palette to avoid collisions) */
  --success:  #10B981;
  --warning:  #F59E0B;
  --danger:   #EF4444;
  --info:     #60A5FA;
}

:root[data-theme="light"] {
  --bg:              #F8FAFC;
  --bg-elevated:     #FFFFFF;
  --bg-glass:        #F1F5F9;
  --border:          #E2E8F0;
  --border-strong:   #CBD5E1;
  --ink:             #0F172A;
  --ink-secondary:   #334155;
  --ink-muted:       #64748B;
  --brand:           #16A34A;
  --brand-bright:    #22C55E;
  --brand-dim:       #15803D;
  /* aurora palette same, but curtains render at lower opacity + heavier blur on light */
}
```

### 3.2 Aurora borealis — THE signature (build this well, everything else follows)

The aurora is **three layered SVG curtains** morphing and drifting across the top half of the landing hero (and optionally, subtly, on Login and Insights screens). Layered green → cyan → violet, softly blurred, with a starfield behind.

**Component structure** — build as `<AuroraSky />`:

```tsx
// src/components/AuroraSky.tsx
import { motion } from 'framer-motion';

export function AuroraSky() {
  return (
    <div className="aurora-root" aria-hidden="true">
      <StarField />
      <svg
        className="aurora-svg"
        viewBox="0 0 1600 900"
        preserveAspectRatio="xMidYMid slice"
      >
        <defs>
          <filter id="aurora-glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="30" />
          </filter>

          <linearGradient id="curtain-1" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#4ADE80" stopOpacity="0" />
            <stop offset="25%"  stopColor="#4ADE80" stopOpacity="0.9" />
            <stop offset="55%"  stopColor="#6EE7B7" stopOpacity="0.85" />
            <stop offset="80%"  stopColor="#22D3EE" stopOpacity="0.7" />
            <stop offset="100%" stopColor="#22D3EE" stopOpacity="0" />
          </linearGradient>

          <linearGradient id="curtain-2" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#22D3EE" stopOpacity="0" />
            <stop offset="30%"  stopColor="#60A5FA" stopOpacity="0.85" />
            <stop offset="60%"  stopColor="#818CF8" stopOpacity="0.8" />
            <stop offset="90%"  stopColor="#A78BFA" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#A78BFA" stopOpacity="0" />
          </linearGradient>

          <linearGradient id="curtain-3" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="#818CF8" stopOpacity="0" />
            <stop offset="50%"  stopColor="#E879F9" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#E879F9" stopOpacity="0" />
          </linearGradient>

          {/* Reflection / mist at bottom */}
          <linearGradient id="mist" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%"   stopColor="#A78BFA" stopOpacity="0.15" />
            <stop offset="100%" stopColor="#050B1F" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Curtain 1 — green→cyan, top layer */}
        <motion.path
          stroke="url(#curtain-1)"
          strokeWidth="140"
          strokeLinecap="round"
          fill="none"
          filter="url(#aurora-glow)"
          initial={{ d: 'M -100 260 Q 400 140, 800 220 T 1700 260' }}
          animate={{
            d: [
              'M -100 260 Q 400 140, 800 220 T 1700 260',
              'M -100 280 Q 400 180, 800 200 T 1700 240',
              'M -100 240 Q 400 120, 800 240 T 1700 280',
              'M -100 260 Q 400 140, 800 220 T 1700 260',
            ],
          }}
          transition={{ duration: 28, repeat: Infinity, ease: 'easeInOut' }}
        />

        {/* Curtain 2 — blue→violet, middle layer, offset in phase */}
        <motion.path
          stroke="url(#curtain-2)"
          strokeWidth="120"
          strokeLinecap="round"
          fill="none"
          filter="url(#aurora-glow)"
          initial={{ d: 'M -100 380 Q 400 260, 800 340 T 1700 380' }}
          animate={{
            d: [
              'M -100 380 Q 400 260, 800 340 T 1700 380',
              'M -100 360 Q 400 300, 800 320 T 1700 360',
              'M -100 400 Q 400 240, 800 360 T 1700 400',
              'M -100 380 Q 400 260, 800 340 T 1700 380',
            ],
          }}
          transition={{ duration: 34, repeat: Infinity, ease: 'easeInOut' }}
        />

        {/* Curtain 3 — pink/magenta, sparse, bottom of aurora area */}
        <motion.path
          stroke="url(#curtain-3)"
          strokeWidth="90"
          strokeLinecap="round"
          fill="none"
          filter="url(#aurora-glow)"
          opacity="0.7"
          initial={{ d: 'M -100 480 Q 400 400, 800 460 T 1700 480' }}
          animate={{
            d: [
              'M -100 480 Q 400 400, 800 460 T 1700 480',
              'M -100 460 Q 400 420, 800 440 T 1700 460',
              'M -100 500 Q 400 380, 800 480 T 1700 500',
              'M -100 480 Q 400 400, 800 460 T 1700 480',
            ],
          }}
          transition={{ duration: 40, repeat: Infinity, ease: 'easeInOut' }}
        />

        {/* Reflection mist at bottom of aurora */}
        <rect x="0" y="500" width="1600" height="200" fill="url(#mist)" />
      </svg>
    </div>
  );
}

function StarField() {
  // 60 randomly-positioned stars with staggered twinkle
  const stars = Array.from({ length: 60 }, (_, i) => ({
    cx: Math.random() * 1600,
    cy: Math.random() * 600,
    r: Math.random() * 1.4 + 0.3,
    delay: Math.random() * 6,
    duration: 3 + Math.random() * 4,
  }));
  return (
    <svg
      className="starfield"
      viewBox="0 0 1600 900"
      preserveAspectRatio="xMidYMid slice"
    >
      {stars.map((s, i) => (
        <motion.circle
          key={i}
          cx={s.cx} cy={s.cy} r={s.r}
          fill="white"
          initial={{ opacity: 0.2 }}
          animate={{ opacity: [0.2, 0.9, 0.2] }}
          transition={{
            duration: s.duration,
            repeat: Infinity,
            delay: s.delay,
            ease: 'easeInOut',
          }}
        />
      ))}
    </svg>
  );
}
```

Container CSS:
```css
.aurora-root {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
  z-index: 0;
}
.aurora-svg, .starfield {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
.starfield { z-index: 1; }
.aurora-svg { z-index: 2; }
```

Under `prefers-reduced-motion`, freeze all `animate` — set to a single static `d` per path, no repeat.

**Placement rules:**
- Landing hero: `<AuroraSky />` absolute-positioned behind the hero content, spanning the full hero height. Content sits at `z-index: 10`.
- Login page: subtler aurora on the left panel (reduce curtain-3, dim overall opacity).
- App-shell screens: **no aurora** — keep them clean and focused. Aurora is a marketing signature, not a distraction on the work surface.
- Optional exception: Insights screen can have a very subtle single-curtain aurora at the top of the page as a "moment" for the AI feature.

### 3.3 Fine-grain dot grid overlay

Above the aurora but below content, a subtle dot grid for texture (like the Stitch reference):
```css
.dot-grid {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle, rgba(255,255,255,0.05) 1px, transparent 1px);
  background-size: 28px 28px;
  z-index: 3;
  pointer-events: none;
}
```

### 3.4 Data-viz palette (charts only)

Aurora hues carry brand + marketing + chart slot 1. Charts use the following fixed-order palette (CVD-safe on dark navy):

```
Slot 1  #4ADE80  aurora green   (brand)
Slot 2  #F59E0B  amber
Slot 3  #22D3EE  aurora cyan
Slot 4  #A78BFA  aurora violet
Slot 5  #EC4899  hot pink
Slot 6  #FB7185  coral
Slot 7  #60A5FA  aurora blue
Slot 8  #FBBF24  gold
```

Sequential ramp: emerald from `#022C22 → #86EFAC`, six stops.

### 3.5 Typography — Lato throughout

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Lato:wght@300;400;700;900&family=JetBrains+Mono:wght@400;500;600&display=swap">
```

- **Lato** everywhere. Weights: 300 (rare, big supporting), 400 (body), 700 (bold), 900 (black).
- **JetBrains Mono** for tabular numbers, timestamps, IDs.

Type scale (use exactly):
```
hero-display    88px  Lato 900   line 0.95  tracking -0.04em
display-lg      64px  Lato 900   line 1.0   tracking -0.035em
display         40px  Lato 700   line 1.1   tracking -0.025em
heading         24px  Lato 700   line 1.25  tracking -0.015em
subheading      18px  Lato 700   line 1.35
body-lg         18px  Lato 400   line 1.55
body            15px  Lato 400   line 1.55
body-sm         13px  Lato 400   line 1.5
label           13px  Lato 700   line 1.4
caption         11px  Lato 700   line 1.4  uppercase  tracking 0.08em
mono-value      32px  JBMono 500  tabular
mono-label      11px  JBMono 500  tabular  uppercase  tracking 0.06em
```

### 3.6 Shape

- Radius: `6px` chips, `10px` buttons, `12px` inputs, `16px` cards, `20px` modals, `9999px` pills.
- 4px grid: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96, 128.
- Cards on landing = glass: `background: var(--bg-glass); border: 1px solid var(--border); backdrop-filter: blur(24px);`. Hover: border brightens, subtle emerald glow at edges.
- App cards = flat `--bg-elevated` on navy.
- Primary button: `background: var(--brand); color: #050B1F; box-shadow: 0 0 40px var(--brand-glow);`. Hover: brightness increases + glow expands.
- Secondary: glass with `--border-strong`.
- Focus ring: `0 0 0 3px var(--brand-wash), 0 0 0 1px var(--brand)`.

### 3.7 Logo — stacked bars with growth arrow

SVG. Four ascending bars in aurora green, small upward arrow lifting off from the tallest bar, tilted ~35° right.

```
viewBox 40x40:
Bar 1: x=6,  y=24, w=5, h=10, fill=#4ADE80 opacity 0.40
Bar 2: x=14, y=18, w=5, h=16, fill=#4ADE80 opacity 0.60
Bar 3: x=22, y=12, w=5, h=22, fill=#4ADE80 opacity 0.80
Bar 4: x=30, y=6,  w=5, h=28, fill=#4ADE80 opacity 1.00

Arrow above bar 4:
Shaft: line (33,4) to (38,-1), 2px stroke #4ADE80, round cap
Head: two 2.5px strokes at the tip
```

Landing hero animation: bars grow from 0 height in stagger (each 400ms, 60ms stagger), then arrow draws in with `pathLength` 0 → 1 over 500ms.

### 3.8 Motion — every animation via Framer Motion

**Aurora curtains** — see 3.2. Always running (frozen under `prefers-reduced-motion`).

**Starfield** — twinkle per star, `prefers-reduced-motion` sets all to static opacity 0.5.

**Landing hero entrance:**
1. Small badge fades in (300ms)
2. Headline reveals word-by-word, 60ms stagger, each word `y: 24, opacity: 0 → 0, 1` over 500ms `[0.16, 1, 0.3, 1]`
3. Subhead fades in 200ms after headline completes
4. Glass prompt card scales in from 0.96 + fades over 400ms
5. CTAs fade + slide up 8px, staggered 60ms

**Page transitions**: 240ms fade + 8px slide + 4px blur (as v3).

**Stat tiles**: number `useSpring` count-up (stiffness 60, damping 20, ~1s). Card fades + slides up 12px, 240ms, staggered 60ms across the row.

**Bar chart entry**: bars grow from 0 width, 50ms stagger, 400ms each. Value labels fade in after.

**Line/area chart**: SVG `pathLength` 0 → 1 over 800ms. Area fill fades in from 0 opacity after path.

**Sidebar hover**: 2px emerald indicator slides in from left over 180ms.

**Row hover**: background transitions to `var(--bg-glass)` over 120ms.

**Card hover**: border to `var(--border-strong)`, translate `y: -2px`, subtle emerald glow, 200ms.

**Button primary hover**: glow blur/spread increases, brightness +5%, 150ms.

**Toast**: spring in from top-right (stiffness 380, damping 30), auto-dismiss 4s.

**Modal**: backdrop fade 200ms, panel scale 0.96 + fade 220ms.

**Scroll reveal** on landing sections: fade + slide up 12px with `whileInView`, `viewport: { once: true, margin: '-100px' }`.

All animations set to `duration: 0.01ms` under `prefers-reduced-motion`.

---

## 4. Project setup

```bash
npm create vite@latest vitta -- --template react-ts
cd vitta
npm install
npm install framer-motion lucide-react react-router-dom @tanstack/react-query zustand recharts clsx tailwind-merge
npm install -D tailwindcss @tailwindcss/vite
```

Set `<html data-theme="dark">` in `index.html`. Include the Google Fonts link.

File structure:
```
src/
  main.tsx
  App.tsx
  index.css                (Tailwind + all CSS custom properties)
  lib/
    utils.ts, format.ts, supabase.ts
  components/
    AuroraSky.tsx          (the drifting northern lights + starfield)
    Logo.tsx               (SVG logo, animated + static variants)
    Button.tsx
    Card.tsx               (glass + elevated variants)
    Input.tsx
    Tag.tsx
    StatTile.tsx
    NumberCountUp.tsx
    Chart/
      BarChart.tsx
      AreaChart.tsx
      Donut.tsx
      Sparkline.tsx
      StackedBar.tsx
    Layout/
      Sidebar.tsx, TopBar.tsx, AppShell.tsx, Toast.tsx
    Landing/
      HeroPrompt.tsx       (glass card with rotating placeholder text)
      SectionReveal.tsx
  screens/
    marketing/ (Landing, Security, Pricing, Sales)
    auth/ (Login)
    app/ (Overview, Transactions, Categories, Merchants, Accounts, Insights, Settings)
  data/
    seed.ts                (real July 2026 transactions)
    categories.ts          (taxonomy + Tier 1 rules)
  hooks/
    useTheme.ts, useCountUp.ts, useReducedMotion.ts
```

---

## 5. Landing page — build first

**Layout, top to bottom:**

### 5.1 Nav bar
Fixed. Translucent navy with backdrop blur. Left: Logo (24px) + "Vitta" (Lato 700, 18px) + optional BETA pill. Right: Product · Pricing · Security · Sign in (ghost) · **Try now** (primary emerald pill).

### 5.2 Hero — THE aurora moment
Min-height: 90vh. Layers back to front:
1. Navy ground (`--bg`)
2. `<AuroraSky />` — the drifting curtains + starfield
3. `.dot-grid` texture overlay
4. Content, centered:
   - Optional small badge: "AI-native · Built for India" (glass pill with emerald ring)
   - **Headline** (88px Lato Black, white, centered, max-width 900px, text-wrap balance): "Every rupee, understood."
   - Subhead (20px Lato 400, `--ink-secondary`, max-width 640px): "Upload your bank statement, GPay, PhonePe, or credit card. Vitta turns raw transactions into a picture you can actually act on."
   - **Glass prompt card** (mimics Stitch input): rounded-20px glass card, 640px max-width, padding 32px. Shows rotating placeholder text every 3s cycling through: "How much did I spend on food last quarter?" · "What subscriptions am I paying for?" · "Am I saving more than last month?". Bottom-left of card: chips "Personal" / "Business". Bottom-right: emerald arrow button. Click arrow → `/login`.
   - CTA pair below the card: "Get started free" (emerald primary with glow) + "Talk to sales" (glass secondary).

### 5.3 Live-demo strip
Full-width, dark ground. Three huge counters side by side, count up on scroll into view: `35%`, `~25`, `95%`. Captions below in `--ink-muted`.

### 5.4 How it works
Three columns with numbered eyebrows (01/02/03): Upload · Parse · Understand. Small SVG illustrations in emerald ink, draw-in on scroll (800ms path animation).

### 5.5 Feature grid
6 glass cards in 3×2 grid. Lucide icon in emerald wash rounded-square, heading (Lato 700 20px), 2-line description. Hover: border brightens, translate `y: -2px`, emerald glow.

Features: Multi-source ingest · Tag once, remember forever · Ask anything (AI Q&A) · Recurring subscription detection · Multi-account · Bank-grade security.

### 5.6 Product screenshot section
Two-column. Left: Lato 700 40px "See your money the way it actually moves." + supporting paragraph. Right: inline mock of the Overview dashboard (stat cards + area chart + top merchants), populated from seed data. Screenshot has a subtle emerald border glow, rounded 16px.

### 5.7 Trust section
Glass card. Left: heading "Your data. Handled with care." + bullets (source PDFs deleted after parsing · encrypted at rest · DPDP-ready · never resold). Right: badge grid.

### 5.8 Testimonial
Single blockquote, Lato 400 italic 32px, centered, max-width 720px. Attribution below in `--ink-muted`.

### 5.9 Pricing
3 glass cards. **Free** (personal, 3 accounts, 6 months history) · **Pro ₹299/mo** (unlimited + AI, middle card has emerald ring emphasis) · **Enterprise** ("Talk to Sales" — no price shown).

### 5.10 Final CTA
Full-width band with a subtler aurora glow behind. Lato Black 64px "Start understanding your spending in 5 minutes." Big emerald button below.

### 5.11 Footer
Four columns of links. Small logo + copyright.

Every section: fade + slide up 12px on scroll into view, staggered per child.

---

## 6. Other screens (concise)

### 6.1 Login (`/login`)
Split. Left 55%: navy + subtle aurora (dimmed, only curtain 1 + 2) + huge Lato Black "Vitta" wordmark + tagline. Right 45%: glass card centered, "Welcome back", "Continue with Google" button (48px emerald with glow), legal caption.

### 6.2 Sales (`/sales`)
Two-column glass form. Fields: Full name, Work email, Company, Team size (segmented control 1-10 / 11-50 / 51-200 / 201+), Use case textarea. Submit → animated emerald checkmark SVG stroke-draw, success state.

### 6.3 App shell — NO AURORA
Fixed left sidebar 240px, `--bg-elevated` on navy. Logo top. Nav: Overview · Transactions · Categories · Merchants · Accounts · Insights · Settings. Active item: 2px emerald left border + emerald ink + subtle wash. Top bar 64px: search (Cmd+K), theme toggle, "Upload statement" emerald primary, avatar.

### 6.4 Overview (`/app`)
- Greeting (Lato 700 32px "Good morning, Varun.")
- 4 stat tiles with count-up numbers, JBMono values
- 6-month spending area chart, emerald gradient fill, SVG path draws in
- Two-column: Category horizontal stacked bar + Top 10 merchants vertical bar
- Recurring subscriptions callout (emerald-wash glass card with Sparkles icon)
- Last 8 transactions preview

### 6.5 Transactions
Sticky filter bar (search Cmd+K, category multi-select, account filter, date range presets, source filter). Full table with inline-editable category pills. Row click → right drawer with full detail (VPA, UPI ref, remark, dedup group).

### 6.6 Categories
Grid of cards. Top border in category color, sparkline trend, total, click → drilldown page (all txns, merchant ranking, monthly trend).

### 6.7 Merchants
Tag-once dictionary. Editable table with applied-to counts, bulk edit.

### 6.8 Accounts
Grid of account cards. Upload button opens modal (drag-drop with emerald border, password prompt if needed, streaming parse progress with animated checkmarks per stage, post-parse review before commit).

### 6.9 Insights — optional subtle aurora
60/40 split. Left: LLM-generated insight cards (Sparkles icon, glass card, emerald wash). Right: chat with Vitta AI, streaming responses, suggestion chips. **Optional**: a single subtle aurora curtain at the very top of this screen as a "moment" for the AI feature. If included, use only curtain-3 (violet/pink) at 40% opacity.

### 6.10 Settings
Tabs: Profile · Data & Privacy · Notifications · Integrations · Danger zone (red accent, requires typing "DELETE" to confirm actions).

---

## 7. Data model (Supabase / Postgres)

```sql
CREATE TABLE accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users NOT NULL,
  bank_name text NOT NULL,
  account_last4 text NOT NULL,
  account_holder text,
  ifsc text,
  account_type text,
  vpas text[] DEFAULT '{}',
  created_at timestamptz DEFAULT now()
);

CREATE TABLE transactions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users NOT NULL,
  account_id uuid REFERENCES accounts NOT NULL,
  txn_date date NOT NULL,
  txn_time time,
  amount numeric(12,2) NOT NULL,
  direction text CHECK (direction IN ('debit','credit')) NOT NULL,
  merchant_raw text NOT NULL,
  merchant_clean text,
  vpa text,
  remark text,
  upi_ref text,
  source text NOT NULL,
  category text,
  is_self_transfer boolean DEFAULT false,
  is_recurring boolean DEFAULT false,
  dedup_group_id uuid,
  mcc text,
  raw_json jsonb,
  created_at timestamptz DEFAULT now()
);
CREATE INDEX ON transactions (user_id, txn_date DESC);
CREATE INDEX ON transactions (upi_ref);

CREATE TABLE merchant_dictionary (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users NOT NULL,
  merchant_key text NOT NULL,
  match_type text CHECK (match_type IN ('exact_name','vpa','name_contains')),
  display_name text,
  category text NOT NULL,
  is_user_tagged boolean DEFAULT true,
  applied_count int DEFAULT 0,
  UNIQUE(user_id, merchant_key, match_type)
);

CREATE TABLE contact_map (
  user_id uuid REFERENCES auth.users,
  phone text,
  contact_name text NOT NULL,
  PRIMARY KEY (user_id, phone)
);

CREATE TABLE upload_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users NOT NULL,
  file_name text NOT NULL,
  source text NOT NULL,
  status text NOT NULL,
  parsed_summary jsonb,
  error text,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE sales_leads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name text, work_email text, company text,
  team_size text, use_case text,
  created_at timestamptz DEFAULT now()
);

-- RLS on every user table
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own rows" ON accounts USING (auth.uid() = user_id);
-- (repeat for transactions, merchant_dictionary, contact_map, upload_jobs)
```

---

## 8. PDF parsers (FastAPI, `/backend`)

`POST /api/parse` — accepts file + `source` type. Returns normalized JSON.

- **GPay PDF** — structured format. Regex on `Paid to X · UPI Transaction ID: NNN · Paid by [Bank]`.
- **PhonePe PDF** — similar structured format.
- **Indian bank PDF** — narration like `HDFC0004699/P SHREYAS GOWDA/XXXXX43681/6361943681-3@axl/UPI/621641459779/mane`. Regex-extract: IFSC prefix, payee name, VPA, UPI ref (12 digits), remark (last `/`-delimited token). Handle password decryption with `pypdf.PdfReader(...).decrypt()`.
- **Credit card PDF** — per-bank templates. Extract MCC when present.

Output shape:
```json
{
  "account": { "bank": "Indian Bank", "last4": "7318", "ifsc": "IDIB000A682" },
  "transactions": [{
    "date": "2026-08-04", "amount": 10000, "direction": "debit",
    "merchant_raw": "P SHREYAS GOWDA", "vpa": "6361943681-3@axl",
    "upi_ref": "621641459779", "remark": "mane"
  }]
}
```

---

## 9. Categorization — 3 tiers, cascading

**Tier 1 — Rules (free, instant):** VPA patterns · merchant name keywords · remark keywords · MCC codes.

**Tier 2 — User dictionary:** Tagged merchants (stored in `merchant_dictionary`) apply to all past + future. If VPA contains a phone number matching `contact_map`, use the saved contact name.

**Tier 3 — LLM suggestion (only when 1 & 2 miss):** Send merchant name, amount, time-of-day, day-of-week, past-frequency to Groq. LLM returns `{ category, confidence }`. If confidence ≥ 0.7, apply auto ("AI-tagged" pill). Below 0.7, surface in Insights review queue. User confirms → becomes a Tier 2 rule.

**Self-transfer detection:** Two transactions on user-owned accounts, same amount, within 48h, opposite directions → both flagged `is_self_transfer = true`. Excluded from spending totals.

**Dedup:** Same UPI ref across sources → one `dedup_group_id`. Fallback: `(amount, date ± 1, direction, merchant fuzzy match ≥ 80%)`. Bank row keeps VPA + remark; GPay row keeps clean merchant name.

---

## 10. AI (Groq API, free tier)

Model: `llama-3.3-70b-versatile`. Env: `GROQ_API_KEY`.

**A. Category suggestion** (Tier 3 above).

**B. Insights feed** — nightly job produces 3-5 cards: recurring subscriptions, anomalies, category shifts, savings opportunities. Prompt template in code, produces JSON `[{title, body, action}]`. Never invent numbers — use only provided data.

**C. Ask anything (text-to-SQL):** Two-step. LLM produces SQL against `transactions_view` for the current user_id. Backend validates (SELECT-only, must reference view, must have user_id clause), executes with a read-only DB role, returns rows. Second LLM call narrates the result. **LLM never does math.**

---

## 11. Security

- RLS on every table.
- Delete source PDFs from Storage after successful parse. Keep normalized rows only.
- HTTPS. No third-party analytics that see transaction content.
- Rate limit LLM endpoints per user.
- DPDP-compliant "delete my data" cascade.

---

## 12. Build order (Claude Code)

1. **Foundation**: Project setup, tokens in `index.css`, Tailwind config. Build `<AuroraSky />` + `<Logo />`. Create `/dev` route showing both. **Ship the aurora perfectly before doing anything else** — if the aurora isn't right, nothing after it will feel right.
2. **Primitives**: Button, Card, Input, Tag, StatTile, NumberCountUp. Add to `/dev`.
3. **Landing hero** (section 5.2) with the aurora underneath. Get this beautiful before the rest of the landing.
4. **Rest of landing**: sections 5.3 → 5.11.
5. **Login page**.
6. **App shell** (sidebar + top bar + empty routes).
7. **Overview** with seed data.
8. **Transactions table** with seed data.
9. **Upload modal** (mocked parse).
10. **Categories, Merchants, Accounts** screens.
11. **Insights** (mocked AI).
12. **Backend FastAPI** — GPay parser first.
13. Wire **real parse endpoint**, then bank statement parser.
14. Wire **LLM (Groq)** for Tier 3 + insights + chat.
15. **Sales page** + form → Supabase.
16. **Settings + data export/delete**.

---

## 13. Seed data

`src/data/seed.ts` with ~80 real transactions from Varun's July 2026 GPay statement. Every dashboard stat, chart, and table populates from this until the backend is wired.

---

## 14. Done criteria

- Aurora renders smoothly at 60fps, no jank on scroll.
- Landing loads under 1s. Lighthouse ≥ 90 on Performance and Accessibility.
- Every animation respects `prefers-reduced-motion`.
- Google sign-in works in one click.
- Upload a real GPay PDF, get a working dashboard within 30 seconds.
- Ask "how much did I spend on food last month" and get a correct number.
- Dark mode is beautiful; light mode also works.

---

## 15. If Claude Code stalls

For the aurora specifically, if Claude Code struggles to get the SVG morph animations right:

1. **[Bolt.new](https://bolt.new)** — best for animated React landings. Paste sections 3.1, 3.2, and 5 verbatim.
2. **[v0.dev](https://v0.dev)** — component-by-component. Great for individual glass cards, stat tiles.
3. **[Lovable](https://lovable.dev)** — full app + Supabase wired in. Best when backend integration stalls.
4. **[Cursor](https://cursor.sh)** or **[Windsurf](https://codeium.com/windsurf)** — same brief in an IDE that has Claude built in.

**Recommended:** use Bolt.new for the aurora landing alone (paste 3.2 as-is — the code is copy-pasteable), then bring the code back into Claude Code for everything else.

---

**Start with Step 1: Build `<AuroraSky />` and `<Logo />` and show them on `/dev`. Get the aurora right first — it's the visual signature everything else builds on.**
