# Vitta — Build Brief v3 (Stitch-inspired dark + violet aurora)

Build a production-grade expense analytics web app for the Indian market. Reference visual language: **Google Stitch's landing page** (stitch.withgoogle.com) — pure black canvas, huge centered serif-weight display, softly-drifting violet aurora glows bleeding in from the edges, glass-surface prompt input at the bottom.

**Read this whole document first, then start with Step 1.** Don't reproduce it back — build it.

---

## 0. Non-negotiables

- **Pure black ground.** Not off-black. `#000000` on the landing and app both.
- **Violet aurora flames** on the landing page — two large blurred gradient blobs bleeding in from the left and right edges, gently drifting in a slow loop. This is THE visual signature.
- **Lato only** for all typography — the same face Slack uses. Loaded from Google Fonts.
- **Every animation via Framer Motion.** No ad-hoc CSS transitions.
- **Dark theme primary.** Light theme exists but is secondary; build dark first.
- **LLM never does arithmetic** — LLM writes SQL, backend runs it, LLM narrates the result.

---

## 1. Product context (unchanged from earlier discussions)

**Vitta** (Sanskrit: वित्त — wealth, finance). Tagline: **"Every rupee, understood."**

Vitta ingests statements from any Indian bank, GPay, PhonePe, and credit cards. Parses them, deduplicates across sources, categorizes with a 3-tier engine (rules → user dictionary → LLM), and gives users a complete AI-narrated view of their spending.

Two audiences:
- Personal users — self-serve signup, upload statements
- Small business / freelancers / enterprise — same product plus a "Talk to Sales" path

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Frontend | **Vite + React 18 + TypeScript** |
| Styling | **Tailwind CSS 4** with CSS custom properties for tokens |
| Animation | **Framer Motion** (mandatory — every animation goes through it) |
| Icons | **Lucide React** |
| Charts | **Recharts** + hand-rolled SVG for custom |
| Router | **React Router v6** |
| State | **Zustand** (client) + **TanStack Query** (server) |
| Backend | **Python FastAPI** (separate service, `/backend`) |
| Database | **Supabase** (Postgres + Auth + Storage) |
| PDF parsing | `pdfplumber`, `pypdf`, `camelot-py` |
| LLM | **Groq** `llama-3.3-70b-versatile` (free tier) + **Gemini 1.5 Flash** fallback |
| Deployment | Vercel + Railway + Supabase |

---

## 3. Design system

### 3.1 Color

Pure black canvas with violet aurora. Everything reads as glass/glow on black.

```css
:root[data-theme="dark"] {
  /* Grounds — true black */
  --bg:              #000000;
  --bg-elevated:     #0A0A0F;
  --bg-glass:        rgba(255,255,255,0.03);   /* card surface */
  --bg-glass-strong: rgba(255,255,255,0.06);   /* hover card */
  --bg-inset:        rgba(255,255,255,0.02);   /* inputs */

  /* Borders — hairlines of white */
  --border:          rgba(255,255,255,0.08);
  --border-strong:   rgba(255,255,255,0.16);
  --border-emphasis: rgba(255,255,255,0.28);

  /* Ink */
  --ink:             #FFFFFF;
  --ink-secondary:   rgba(255,255,255,0.72);
  --ink-muted:       rgba(255,255,255,0.50);
  --ink-faint:       rgba(255,255,255,0.28);

  /* Aurora palette — used for the moving flames + brand accents */
  --aurora-1:        #8B5CF6;   /* violet — primary */
  --aurora-2:        #A78BFA;   /* light violet */
  --aurora-3:        #C084FC;   /* soft purple */
  --aurora-4:        #EC4899;   /* magenta warmth */
  --aurora-5:        #6366F1;   /* indigo edge */

  /* Brand — light violet reads best as CTA on true black */
  --brand:           #A78BFA;
  --brand-bright:    #C4B0FC;
  --brand-dim:       #8B5CF6;
  --brand-wash:      rgba(167,139,250,0.08);
  --brand-glow:      rgba(167,139,250,0.35);

  /* Semantic */
  --success:  #10B981;
  --warning:  #F59E0B;
  --danger:   #EF4444;
  --info:     #60A5FA;
}

:root[data-theme="light"] {
  --bg:              #FAFAFA;
  --bg-elevated:     #FFFFFF;
  --bg-glass:        #F4F4F5;
  --border:          #E5E5E5;
  --border-strong:   #D4D4D4;
  --ink:             #0A0A0F;
  --ink-secondary:   #3F3F46;
  --ink-muted:       #71717A;
  --brand:           #7C3AED;
  --brand-bright:    #8B5CF6;
  --brand-dim:       #6D28D9;
  /* aurora is the SAME on light; the blobs drift on a light canvas
     with lower opacity and heavier blur */
}
```

### 3.2 The aurora flames — THE signature

Reference: Stitch's landing hero, purple/violet blobs bleeding in from both edges, slowly drifting in a loop.

Implementation (in a `<Aurora />` component, absolute-positioned inside the landing hero and any app screen that uses it):

```tsx
// Two large radial gradients, blurred, animated via Framer Motion
<div className="aurora-root">
  <motion.div
    className="aurora-blob aurora-left"
    animate={{
      x: [0, 60, -20, 0],
      y: [0, -40, 30, 0],
      scale: [1, 1.15, 0.95, 1],
    }}
    transition={{ duration: 24, repeat: Infinity, ease: 'easeInOut' }}
    style={{
      background: 'radial-gradient(circle, rgba(139,92,246,0.55) 0%, rgba(167,139,250,0.35) 30%, rgba(236,72,153,0.15) 60%, transparent 75%)',
      filter: 'blur(80px)',
      position: 'absolute',
      left: '-20%', top: '10%',
      width: '70%', height: '80%',
      pointerEvents: 'none',
    }}
  />
  <motion.div
    className="aurora-blob aurora-right"
    animate={{
      x: [0, -50, 30, 0],
      y: [0, 40, -30, 0],
      scale: [1, 0.9, 1.1, 1],
    }}
    transition={{ duration: 28, repeat: Infinity, ease: 'easeInOut' }}
    style={{
      background: 'radial-gradient(circle, rgba(99,102,241,0.55) 0%, rgba(139,92,246,0.35) 35%, rgba(167,139,250,0.15) 60%, transparent 75%)',
      filter: 'blur(90px)',
      position: 'absolute',
      right: '-20%', top: '20%',
      width: '70%', height: '80%',
      pointerEvents: 'none',
    }}
  />
</div>
```

Wrap the black canvas with a fine dot grid overlay for texture — same as Stitch's landing:

```css
.dot-grid {
  background-image: radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px);
  background-size: 24px 24px;
}
```

Under `prefers-reduced-motion`, replace `animate` with a static position — blobs stay in place.

### 3.3 Data-viz palette (charts only)

Aurora hues carry brand and marketing. Charts use this validated CVD-safe palette in fixed order:

```
Slot 1  #A78BFA  light violet  (brand-adjacent)
Slot 2  #F59E0B  amber
Slot 3  #10B981  emerald
Slot 4  #60A5FA  sky
Slot 5  #EC4899  pink
Slot 6  #34D399  mint
Slot 7  #FB7185  coral
Slot 8  #FBBF24  gold
```

Sequential ramp: violet from `#1E1B4B → #C4B5FD`, six steps.

### 3.4 Typography — Lato throughout

Load once:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Lato:wght@300;400;700;900&family=JetBrains+Mono:wght@400;500;600&display=swap">
```

- **Lato** for everything — display, headings, body, buttons, labels.
- **JetBrains Mono** for numbers in columns, timestamps, IDs. Use `font-variant-numeric: tabular-nums`.
- Weights: 300 (rare — big display supporting text), 400 (body), 700 (bold, buttons), 900 (black — hero display).

Type scale (use exactly these):
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

The hero on the landing page uses `hero-display` (88px Lato Black) — exactly like the Stitch "Design at the speed of AI" moment.

### 3.5 Shape

- Radius: `6px` chips, `10px` buttons, `12px` inputs, `16px` cards, `20px` modals, `9999px` pills. On the landing, the prompt-style hero input uses `20px` radius (matches Stitch).
- 4px grid: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96, 128.
- Cards on the landing = glass surfaces: `background: var(--bg-glass); border: 1px solid var(--border); backdrop-filter: blur(20px);`. On hover: border brightens.
- App-shell cards = flat `--bg-elevated` on black.
- Buttons — primary is violet on black with a subtle glow: `background: var(--brand); color: #000; box-shadow: 0 0 40px var(--brand-glow);`. Secondary is glass: `background: var(--bg-glass); border: 1px solid var(--border-strong); color: white;`.
- Focus ring: `box-shadow: 0 0 0 3px var(--brand-wash), 0 0 0 1px var(--brand);`.

### 3.6 Logo — stacked bars with growth arrow

Draw as SVG. Four ascending bars in the brand violet, with a small upward-pointing arrow lifting off from the tallest bar. Arrow tilted ~35° right.

```
SVG (viewBox 40x40):

Bar 1: x=6,  y=24, w=5, h=10, fill=#A78BFA opacity 0.35
Bar 2: x=14, y=18, w=5, h=16, fill=#A78BFA opacity 0.55
Bar 3: x=22, y=12, w=5, h=22, fill=#A78BFA opacity 0.78
Bar 4: x=30, y=6,  w=5, h=28, fill=#A78BFA opacity 1.0

Arrow above bar 4:
- Shaft: line from (33,4) to (38,-1), 2px stroke #A78BFA, round cap
- Head: two 2.5px strokes forming the arrow point at (38,-1)
```

Used at:
- 20px (nav / favicon)
- 32px (top bar, marketing nav)
- 96px (landing hero, animated in with bars growing and arrow drawing after)

### 3.7 Motion — every animation via Framer Motion

**Aurora blobs** — see 3.2, always running (except under `prefers-reduced-motion`).

**Landing hero entrance** — on mount:
1. Small "STITCH-like" pill badge fades in at top (0.3s)
2. Hero headline reveals word-by-word with 60ms stagger, each word `y: 20, opacity: 0 → 0, 1`, 500ms per word ease-out
3. Subhead fades in after (0.2s delay after headline)
4. CTAs fade + slide up (0.3s after subhead, 60ms stagger between the two)

**Page transitions** — 240ms fade + 8px slide + 4px blur:
```
initial: { opacity: 0, y: 8, filter: 'blur(4px)' }
animate: { opacity: 1, y: 0, filter: 'blur(0px)' }
exit:    { opacity: 0, y: -4, filter: 'blur(2px)' }
transition: { duration: 0.24, ease: [0.16, 1, 0.3, 1] }
```

**Stat tile numbers** — `useSpring` count-up from 0 to target (stiffness 60, damping 20, ~1s).

**Bar chart entry** — bars grow from 0 width, 50ms stagger per row, 400ms each with `[0.22, 1, 0.36, 1]`. Labels fade in after bar completes.

**Line/area chart** — SVG `pathLength` from 0 to 1 over 800ms; area fill fades in from 0 after path completes.

**Sidebar hover** — 2px violet indicator slides in from left over 180ms.

**Row hover in tables** — background transitions to `var(--bg-glass)` over 120ms.

**Card hover** — border color transitions to `var(--border-strong)`, subtle `y: -2px` translate, 200ms.

**Button primary hover** — glow intensifies (increase `box-shadow` blur/opacity) and slight brightness bump, 150ms.

**Toast** — spring in from top-right (stiffness 380, damping 30), auto-dismiss 4s.

**Modal** — backdrop fades in 200ms, panel scales from 0.96 + fades over 220ms.

**Scroll reveal** on landing sections — every section fades + slides up 12px with `whileInView`, `viewport: { once: true, margin: '-100px' }`.

All animations reduce to `duration: 0.01ms` under `prefers-reduced-motion`.

---

## 4. Project setup

```bash
npm create vite@latest vitta -- --template react-ts
cd vitta
npm install
npm install framer-motion lucide-react react-router-dom @tanstack/react-query zustand recharts clsx tailwind-merge
npm install -D tailwindcss @tailwindcss/vite
```

Set `<html data-theme="dark">` by default. Include Google Fonts links in `index.html`.

File structure:
```
src/
  main.tsx
  App.tsx
  index.css               (Tailwind + all CSS custom properties)
  lib/
    utils.ts              (cn helper)
    format.ts             (₹ formatter, dates)
    supabase.ts
  components/
    Aurora.tsx            (the drifting flames)
    Logo.tsx              (SVG logo, animated variant + static)
    Button.tsx
    Card.tsx              (glass variant + elevated variant)
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
      Sidebar.tsx
      TopBar.tsx
      AppShell.tsx
      Toast.tsx
    Landing/
      HeroPrompt.tsx      (the big glass input at bottom of hero, Stitch-style)
      SectionReveal.tsx   (whileInView wrapper)
  screens/
    marketing/
      Landing.tsx
      Security.tsx
      Pricing.tsx
      Sales.tsx
    auth/
      Login.tsx
    app/
      Overview.tsx
      Transactions.tsx
      Categories.tsx
      Merchants.tsx
      Accounts.tsx
      Insights.tsx
      Settings.tsx
  data/
    seed.ts               (real July 2026 GPay transactions)
    categories.ts         (taxonomy + Tier 1 rules)
  hooks/
    useTheme.ts
    useCountUp.ts
    useReducedMotion.ts
```

---

## 5. Landing page — Stitch-inspired, build first

**Layout, top to bottom:**

### 5.1 Nav bar
- Fixed, translucent black with backdrop blur.
- Left: Logo (20px) + "Vitta" (Lato 700, 16px) + small "BETA" pill (violet wash, JBMono 10px caps).
- Right: text links (Product · Pricing · Security), then "Sign in" (ghost), then "Try now" primary pill button (violet).
- On scroll: nav gets a hairline bottom border.

### 5.2 Hero — THE Stitch moment
- Full viewport height minus nav (min 90vh).
- Pure black canvas with `.dot-grid` overlay + `<Aurora />` component behind everything.
- Center content vertically and horizontally.
- Optional small badge at top: "AI-native · Built for India" (violet ring, glass background).
- **Headline**: 88px Lato Black white, centered, max-width 900px, text-wrap balance. Copy: **"Every rupee, understood."**
- Subhead: 20px Lato 400 in `--ink-secondary`, centered, max-width 640px, `margin-top: 24px`. Copy: **"Upload your bank, GPay, PhonePe, or credit card statement. Vitta turns raw transactions into a picture you can actually act on."**
- **Below subhead: the Stitch-style prompt-shaped card** — a large glass card mimicking the "What native mobile app shall we design?" input from Stitch. But instead of an input, it's a demo prompt display showing example questions Vitta can answer:
  - Rotating placeholder text every 3s: "How much did I spend on food last quarter?" · "What subscriptions am I paying for?" · "Am I saving more than last month?"
  - Two chip toggles at the bottom-left of the card: "Personal" · "Business" (like Stitch's "App"/"Web" chips)
  - Bottom-right of card: a small violet arrow button (like Stitch's send button)
  - Card style: `background: var(--bg-glass); border: 1px solid var(--border); backdrop-filter: blur(20px); border-radius: 20px; padding: 32px;`
  - On hover: border brightens, subtle glow appears
  - Clicking the arrow button = navigates to `/login`
- CTAs below the card: **"Get started free"** (primary violet with glow) + **"Talk to sales"** (glass secondary).

### 5.3 Live-demo strip
Right below hero. Full-width. Three big animated stats side by side. Numbers count up on scroll into view.
- `35%` — auto-categorized from name alone (industry baseline)
- `~25` — unique payees per user per month
- `95%` — bank statement coverage of your finances

Fraunces-like heavy weight (use Lato Black 88px), caption below in `--ink-muted`.

### 5.4 How it works
Three columns, numbered eyebrows (01 · 02 · 03), Lato 700 headings, Lato 400 body.
1. **Upload** — Drop your bank PDF, GPay export, or credit card statement. Passwords supported.
2. **Parse** — Vitta reads narrations, VPAs, remarks, MCCs. Multi-source dedup via UPI ref.
3. **Understand** — 3-tier categorization + AI narration. Ask anything in plain English.

Each column has a small SVG illustration in violet ink that animates on scroll into view (draw-in, 800ms).

### 5.5 Feature grid
6 cards in 3×2 grid. Each is a glass card with:
- Lucide icon in violet-wash rounded square (32px)
- Heading (Lato 700, 20px)
- 2-line description (Lato 400, 14px, `--ink-secondary`)
- Cards hover: border brightens, translate `y: -2px`, subtle violet glow.

Features: Multi-source ingest · Tag once, remember forever · Ask anything (AI Q&A) · Recurring subscription detection · Multi-account handling · Bank-grade security.

### 5.6 Product screenshot section
Two-column. Left: Lato 700 40px "See your money the way it actually moves." + supporting paragraph. Right: real dashboard screenshot mock built inline (stat cards + area chart + category breakdown, populated from seed data). Screenshot has a subtle violet border glow and rounds at 16px.

### 5.7 Trust section
Full-width glass card. Left: heading "Your data. Handled with care." + bullet list (source PDFs deleted after parsing · encrypted at rest · DPDP-ready · never resold). Right: small badge grid (Encrypted · DPDP-ready · SOC 2 in progress · Row-level security).

### 5.8 Testimonial
Single large blockquote. Lato 400 italic 32px, centered, max-width 720px. Attribution: name + role in `--ink-muted`.

### 5.9 Pricing
3 columns, glass cards. **Free** (personal, 3 accounts, 6 months history), **Pro** ₹299/mo (unlimited accounts + history + AI insights) — middle card has violet ring emphasis, **Enterprise** ("Talk to Sales" — no price shown, contact CTA).

### 5.10 Final CTA
Full-width dark band with an aurora glow behind. Massive Lato Black 64px "Start understanding your spending in 5 minutes." Big violet button below. Small caption: "Free forever for personal use."

### 5.11 Footer
Four columns of links. Small logo + copyright at bottom. Hairline top border.

Every section on scroll: fades + slides up 12px, staggered per child.

---

## 6. Other screens (concise — same content as v2)

### 6.1 Login (`/login`)
Split-panel. Left 55%: black + aurora + huge Lato Black "Vitta" wordmark + tagline. Right 45%: glass card centered, "Welcome back", "Continue with Google" button (48px violet with glow), legal caption.

### 6.2 Sales (`/sales`)
Two-column. Left: value copy. Right: glass form card with fields (Full name, Work email, Company, Team size segmented control, Use case textarea). Submit → animated violet checkmark, success message.

### 6.3 App shell
Fixed left sidebar 240px, `--bg-elevated` on black. Logo top. Nav: Overview · Transactions · Categories · Merchants · Accounts · Insights · Settings. Active item: 2px violet left border + violet ink + subtle wash. Top bar 64px: search (Cmd+K), theme toggle, "Upload statement" violet button, avatar.

### 6.4 Overview (`/app`)
- Greeting (Lato 700 32px "Good morning, Varun.")
- 4 stat tiles with count-up numbers
- 6-month spending area chart, violet gradient fill, path draws in
- Two-column: Category horizontal stacked bar + Top 10 merchants vertical bars
- Recurring subscriptions callout (violet-wash glass card with Sparkles icon)
- Last 8 transactions preview

### 6.5 Transactions (`/app/transactions`)
Sticky filter bar. Full table with inline-editable category chips. Row hover shows action buttons. Click row → right-side drawer with full detail (VPA, UPI ref, remark, dedup group, raw statement line).

### 6.6 Categories (`/app/categories`)
Grid of category cards. Top border in category color, sparkline trend, total spend, click → drilldown.

### 6.7 Merchants (`/app/merchants`)
The tag-once dictionary. Editable table. Applied-to count. Bulk edit.

### 6.8 Accounts (`/app/accounts`)
Grid of account cards. "Upload new" per account and globally. Upload modal: drag-drop with violet border, password prompt if needed, streaming parse progress (each check-item animates in), post-parse review before commit.

### 6.9 Insights (`/app/insights`)
60/40 split. Left: LLM-generated insight cards (Sparkles icon, glass card, violet wash, actions). Right: chat with Vitta AI, streaming responses, suggestion chips.

### 6.10 Settings (`/app/settings`)
Tabs: Profile · Data & Privacy · Notifications · Integrations · Danger zone (with red accent).

---

## 7. Data model, PDF parsers, categorization, AI

Everything in v2 stays (Postgres schema, GPay/PhonePe/bank/CC parsers, 3-tier categorization, self-transfer detection, dedup via UPI ref, Groq LLM for Tier 3 + insights + text-to-SQL). Copy those sections from v2 verbatim into the codebase.

Key rules (repeating because critical):
- LLM never does math.
- User's own accounts + own VPAs → self-transfer detection excludes from spending totals.
- Merchant dictionary is per-user and grows with every tag.
- Delete source PDFs after successful parse.
- RLS on every Supabase table.

---

## 8. Build order — for Claude Code

Do these one at a time. After each step, show the result before proceeding.

1. **Foundation**: Project setup, design tokens in `index.css`, Tailwind config. Create `<Aurora />` component and `<Logo />` component. Build a `/dev` route that shows both.
2. **Primitives**: Button (primary/secondary/ghost), Card (glass/elevated), Input, Tag, StatTile, NumberCountUp. Add them to `/dev`.
3. **Landing hero + aurora**: Just section 5.2 first. When this feels right, everything else follows.
4. **Rest of landing**: All sections top to bottom.
5. **Login page**.
6. **App shell** (sidebar + top bar + empty routes).
7. **Overview with seed data**: All charts working, all animations wired.
8. **Transactions table with seed data**.
9. **Upload modal (mocked parse)**.
10. **Categories, Merchants, Accounts** screens.
11. **Insights (mocked AI)**.
12. **Backend FastAPI**: GPay parser first.
13. **Wire real parse endpoint**, then bank statement parser.
14. **Wire LLM (Groq)** for Tier 3 + insights + chat.
15. **Sales page** + Talk to Sales form → Supabase.
16. **Settings + data export/delete**.

---

## 9. Seed data

Include `src/data/seed.ts` with the ~80 real transactions from Varun's July 2026 GPay statement. Every stat tile, chart, and table on Overview populates from this until the backend is wired.

Sample:
```ts
export const seedTransactions = [
  { date: '2026-07-03', merchant: 'SWIGGY INSTAMART', vpa: 'swiggy.payu@axisb',
    amount: 150, direction: 'debit', category: 'Groceries',
    source: 'gpay_pdf', upi_ref: '618483978561' },
  // ... 80+ more, real data
];
```

---

## 10. What "done" looks like for MVP

- Landing loads under 1s, Lighthouse ≥ 90.
- Aurora blobs drift smoothly. No layout shift.
- Hero headline reveals word-by-word on first load.
- Google sign-in works in one click.
- Upload a real GPay PDF, see a working dashboard within 30 seconds.
- Every chart animates in. Every stat counts up.
- Ask "how much did I spend on food last month" and get a correct number.
- Dark mode is beautiful; light mode also works.
- No screen anywhere looks like Slack, Notion, or a generic Tailwind template.

---

## 11. If Claude Code struggles with any part

Some parts of this brief are visually ambitious. If a specific step is stalling in Claude Code, hand it to a specialist tool:

| Tool | Best for | Free tier |
|---|---|---|
| **[Bolt.new](https://bolt.new)** by StackBlitz | Full-stack React apps with heavy animation. Best for the landing page specifically — hand it the landing section verbatim. | Yes (limited daily prompts) |
| **[v0.dev](https://v0.dev)** by Vercel | Component-by-component. Great for individual screens or a specific card layout. Copy the component spec, paste, iterate. | Yes (free credits monthly) |
| **[Lovable](https://lovable.dev)** | Full app with Supabase backend wired in. Point-and-click iteration. Best if Claude Code stalls on backend integration. | Yes (limited daily messages) |
| **[Windsurf](https://codeium.com/windsurf)** by Codeium | IDE with Claude built in. Alternative to Cursor. Very generous free tier. | Yes |
| **[Cursor](https://cursor.sh)** | IDE with Claude/GPT. If Claude Code hits limits, switch to Cursor with the same brief. | Yes (limited requests) |

**Recommended path if Claude Code stalls:**
1. Use **Bolt.new** for the landing page alone (paste sections 3.1, 3.2, 3.4, 3.5, and 5 as the prompt). Bolt is exceptional at animated React landings.
2. Use **v0.dev** to generate individual components (StatTile, Chart, Card) — copy the spec from section 3 and 6.
3. Use **Lovable** for the app + backend (Supabase integration is native there).
4. Continue product logic (parsers, categorization, LLM) back in **Claude Code** or **Cursor**.

---

**Start with Step 1 (Foundation). Build the Aurora + Logo first. Show me the `/dev` route before moving to the landing hero.**
