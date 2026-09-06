# Vitta — Build Brief (v2, for Claude Code)

Build a production-grade expense analytics web application for the Indian market. It ingests statements from any Indian bank, UPI app, or credit card and turns raw transactions into an intelligent, categorized, AI-narrated view of the user's financial life.

**Read this entire document first, then start with Step 0.** Don't reproduce it back — build it.

---

## 0. What we're NOT doing (guardrails)

- **Do NOT copy Slack, Notion, Linear, or Stripe visual patterns.** This product has its own identity.
- **Do NOT use Lato, Manrope, or Inter alone for display.** The display face is a serif (see typography).
- **Do NOT use aubergine/purple as primary.** Primary is emerald green.
- **Do NOT use gradients on buttons or cards.** Solid fills only.
- **Do NOT use rounded-2xl / rounded-3xl everywhere.** Modest radius, see tokens.
- **Do NOT let the AI do arithmetic.** LLM produces SQL → backend runs it → LLM narrates the result.

---

## 1. Product

**Vitta** (Sanskrit: वित्त — wealth, finance). Tagline: **"Every rupee, understood."**

Users: (a) Indian consumers who use GPay/PhonePe + 1-3 bank accounts + a credit card. (b) Small businesses, freelancers, proprietors — same product, plus multi-account handling and a "Talk to Sales" enterprise flow.

The wedge: no consumer product today parses **multi-source Indian statements** (bank + GPay + PhonePe + credit card) with real AI categorization. Walnut is dead, Fi/Jupiter only work with their own accounts, B2B parsers (Perfios) don't sell to individuals. That gap is what Vitta fills.

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Frontend | **Vite + React 18 + TypeScript** |
| Styling | **Tailwind CSS 4** with design tokens defined as CSS custom properties |
| Animation | **Framer Motion** (all animations go through it — no ad-hoc CSS transitions) |
| Icons | **Lucide React** |
| Charts | **Recharts** for standard, hand-rolled SVG for custom (sparklines, category donuts) |
| Router | **React Router v6** |
| State | **Zustand** for client state, **TanStack Query** for server state |
| Backend | **Python FastAPI** (separate service — spawn it as `/backend`) |
| Database | **Supabase** (Postgres + Auth + Storage) |
| PDF parsing | `pdfplumber`, `pypdf` (password decrypt), `camelot-py` (tables) |
| LLM | **Groq** (`llama-3.3-70b-versatile`, free tier) primary, **Gemini 1.5 Flash** fallback |
| Deployment | Vercel (frontend), Railway (FastAPI), Supabase (managed) |

---

## 3. Design system — the identity

This is the **entire visual direction**. Don't deviate.

### 3.1 Color

Dark theme is the **primary experience**. Light is a proper afterthought that also works, not a mirror.

```css
:root[data-theme="dark"] {
  /* Grounds */
  --bg:            #0A0E1A;   /* deep obsidian, subtle blue undertone */
  --bg-elevated:   #131826;   /* cards, elevated surfaces */
  --bg-subtle:     #0F1420;   /* nested surfaces */
  --bg-inset:      #050810;   /* inputs, code blocks */

  /* Borders */
  --border:        #1F2537;
  --border-strong: #2A3149;
  --border-emphasis: #3A4262;

  /* Ink */
  --ink:           #F4F5F8;
  --ink-secondary: #C4C8D4;
  --ink-muted:     #8A90A2;
  --ink-faint:     #5A6076;

  /* Accents — emerald primary, amber secondary, violet tertiary */
  --accent:            #10B981;   /* emerald — brand, primary CTA, growth */
  --accent-bright:     #34D399;   /* hover */
  --accent-dim:        #059669;   /* active/pressed */
  --accent-wash:       rgba(16,185,129,0.10);
  --accent-glow:       rgba(16,185,129,0.28);

  --amber:             #F59E0B;   /* highlights, warmth, category */
  --amber-wash:        rgba(245,158,11,0.10);

  --violet:            #A78BFA;   /* AI, insights */
  --violet-wash:       rgba(167,139,250,0.10);

  /* Semantic */
  --success:    #10B981;
  --warning:    #F59E0B;
  --danger:     #EF4444;
  --info:       #60A5FA;
}

:root[data-theme="light"] {
  --bg:            #FAFAF9;
  --bg-elevated:   #FFFFFF;
  --bg-subtle:     #F4F4F2;
  --bg-inset:      #EEEEEC;
  --border:        #E7E5E4;
  --border-strong: #D6D3D1;
  --border-emphasis: #A8A29E;
  --ink:           #0C0A09;
  --ink-secondary: #44403C;
  --ink-muted:     #78716C;
  --ink-faint:     #A8A29E;
  --accent:        #059669;
  --accent-bright: #10B981;
  --accent-dim:    #047857;
  --accent-wash:   rgba(5,150,105,0.08);
  --amber:         #D97706;
  --violet:        #7C3AED;
  /* semantic same */
}
```

### 3.2 Data-viz palette (CVD-validated, use in fixed order)

```
Slot 1  #10B981  emerald  (brand)
Slot 2  #F59E0B  amber
Slot 3  #60A5FA  sky
Slot 4  #A78BFA  violet
Slot 5  #F472B6  pink
Slot 6  #FB7185  coral
Slot 7  #34D399  mint
Slot 8  #FBBF24  gold
```

Sequential ramp for magnitudes: emerald `#022C22 → #6EE7B7`, six stops.

### 3.3 Typography — editorial serif display + modern sans body

Load once in `index.html`:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700;9..144,800&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap">
```

- **Fraunces** — variable serif, used for display only (hero, page headings, hero stat values). Its optical-size axis is the key move: use `font-optical-sizing: auto` and let it shift character on big sizes. Nothing else in Indian fintech uses a serif — that's the point.
- **Inter** — body, UI labels, navigation, buttons. Standard, dependable.
- **JetBrains Mono** — every number that appears in a column, every timestamp, every ID. Use `font-variant-numeric: tabular-nums`.

Weights actually used:
- Fraunces: 500 (headings), 600 (emphasized), 800 (hero display)
- Inter: 400 (body), 500 (buttons/labels), 600 (bold emphasis)
- JetBrains Mono: 400 (numbers in tables), 500 (stat tile values), 600 (rare)

Type scale (use exactly these; don't invent):
```
hero-display     72px  Fraunces 800  line 0.95  tracking -0.03em
display-lg       48px  Fraunces 700  line 1.05  tracking -0.025em
display          32px  Fraunces 600  line 1.1   tracking -0.02em
heading          22px  Fraunces 600  line 1.25  tracking -0.01em
subheading       17px  Inter    600  line 1.3
body-lg          17px  Inter    400  line 1.55
body             15px  Inter    400  line 1.55
body-sm          13px  Inter    400  line 1.5
label            13px  Inter    500  line 1.4
caption          11px  Inter    500  line 1.4  uppercase  tracking 0.08em
mono-value       28px  JBMono   500  tabular
mono-label       11px  JBMono   500  tabular  uppercase  tracking 0.06em
```

### 3.4 Shape & rhythm

- Radius: `4px` chips, `6px` buttons, `8px` inputs, `10px` cards, `14px` modals, `9999px` pills. Nothing above 14 except pills.
- 4px grid: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96.
- Card elevation is **borders + subtle inner glow**, not shadows. Cards look like: `background: var(--bg-elevated); border: 1px solid var(--border);`. On hover, `border-color: var(--border-strong)` and a very faint inset box-shadow.
- Focus ring: `box-shadow: 0 0 0 3px var(--accent-glow)`, never a browser default outline.

### 3.5 Logo — stacked bars WITH growth arrow

Draw as SVG. Four ascending vertical bars, all emerald. **Above the tallest bar, a small upward-pointing arrow in emerald**, tilted slightly right (about 35° from vertical). Arrow head hangs above the tallest bar as if it's about to lift off.

```
SVG spec (viewBox 40x40):

Four bars, gap 3px, widths 5px each:
  bar 1: x=6,  y=24, h=10, fill=emerald 40% opacity
  bar 2: x=14, y=18, h=16, fill=emerald 60% opacity
  bar 3: x=22, y=12, h=22, fill=emerald 80% opacity
  bar 4: x=30, y=6,  h=28, fill=emerald 100%

Above bar 4, a slim arrow:
  Line from (33,4) to (37,-1) — 2px stroke, emerald, round cap
  Arrow head: two 2.5px strokes at 90° at (37,-1)
```

Same SVG used at 20px (nav / favicon), 28px (top bar), 96px (marketing hero, animated in).

The bars represent data; the arrow represents growth. Together: "your money, growing under Vitta."

### 3.6 Motion — every animation via Framer Motion

Base principles: **subtle, functional, respect `prefers-reduced-motion`**. Never gratuitous. Every duration under 400ms except the specific "moments" listed.

**Global page transition** (route change):
```
initial: { opacity: 0, y: 8, filter: 'blur(4px)' }
animate: { opacity: 1, y: 0, filter: 'blur(0px)' }
exit:    { opacity: 0, y: -4, filter: 'blur(2px)' }
transition: { duration: 0.28, ease: [0.16, 1, 0.3, 1] }
```

**Sidebar item hover**: 2px emerald indicator slides in from left, 180ms.

**Stat tile mount**: number counts up from 0 to target using `useSpring` (stiffness 60, damping 20), takes ~1s. Card itself fades + slides up 12px, 240ms, staggered 60ms across the row.

**Bar chart entry**: bars grow from 0 width, staggered 50ms per row, each 400ms, ease `[0.22, 1, 0.36, 1]`. Value labels fade in after bar completes.

**Line/area chart**: SVG `pathLength` from 0 to 1 over 800ms, area fill fades in from 0 opacity after path completes.

**Row hover in tables**: `background-color` transition 120ms, no other change.

**Card hover** (feature cards, insight cards): border-color transition to `--border-strong` (150ms) + `y: -2px` translate (200ms).

**Toast**: spring in from top-right (`stiffness: 380, damping: 30`), auto-dismiss after 4s with fade + slide out.

**Modal**: backdrop fades in 200ms, panel scales from 0.96 with fade over 220ms.

**Ambient background** on landing hero: three large blurred emerald blobs positioned behind the headline, gently drifting via `animate` on `x/y` with 20-30s duration and `repeat: Infinity, repeatType: 'mirror'`. Reduces to nothing under `prefers-reduced-motion`.

---

## 4. Project setup

Run these first:

```bash
npm create vite@latest vitta -- --template react-ts
cd vitta
npm install
npm install framer-motion lucide-react react-router-dom @tanstack/react-query zustand recharts clsx tailwind-merge
npm install -D tailwindcss@next @tailwindcss/vite
```

`vite.config.ts` — add the Tailwind plugin.

`src/index.css` — import Tailwind and define ALL CSS custom properties from section 3.1 as top-level `:root[data-theme="dark"]` and `:root[data-theme="light"]` blocks. Set `<html data-theme="dark">` by default in `index.html`.

Create this file structure:

```
src/
  main.tsx
  App.tsx
  index.css
  lib/
    utils.ts           (clsx + tailwind-merge helper `cn`)
    format.ts          (₹ formatter, date formatter)
    supabase.ts        (client)
  components/
    Logo.tsx           (the SVG logo)
    Button.tsx
    Card.tsx
    Input.tsx
    Tag.tsx
    StatTile.tsx
    Chart/
      BarChart.tsx
      AreaChart.tsx
      Donut.tsx
      Sparkline.tsx
    Layout/
      Sidebar.tsx
      TopBar.tsx
      AppShell.tsx
      Toast.tsx
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
    seed.ts            (real July 2026 data for demo)
    categories.ts      (category taxonomy + rules)
  hooks/
    useTheme.ts
    useCountUp.ts
```

---

## 5. Screens — build in this order

Start each screen as a static implementation using **seed data** (real July 2026 GPay statement transactions — provided in `src/data/seed.ts`). Wire up the backend in Phase 2.

### 5.1 Landing (`/`) — build first

Full-height page. Structure top to bottom:

1. **Nav bar** — fixed top, translucent obsidian with backdrop blur. Left: Logo (28px) + "Vitta" wordmark (Inter 600). Right: Product · Pricing · Security · Sign in (ghost) · Get started (emerald primary).
2. **Hero** — 720px min-height. Ambient emerald blobs drifting behind. 72px Fraunces 800 headline "Every rupee, understood." Subhead 20px Inter 400 in `--ink-secondary`: "Vitta reads statements from any Indian bank, UPI app, or credit card — and turns them into a picture you can actually act on." Two CTAs. Right side: dashboard screenshot mock (build inline — 3 stat cards + a mini area chart).
3. **The problem strip** — 3 huge stats side by side. Numbers count up on scroll into view: `35%` (auto-categorized from name alone), `~25` (unique payees per user), `95%` (bank statement coverage). Fraunces 800 for the numbers, Inter 500 caption below.
4. **How it works** — 3 columns with numbered eyebrows (01, 02, 03), Fraunces subheadings, Inter body. Each column has a small animated illustration (SVG that plays on scroll into view).
5. **Feature grid** — 6 cards in 3×2 grid. Each: Lucide icon in emerald wash circle, heading, 2-line description. Cards hover to lift 2px + border brighten.
6. **Trust section** — dark card with emerald accent border on left. Bulleted benefits. Small badges: Encrypted at rest · DPDP-ready · Source files deleted after parsing · No data resale.
7. **Testimonial** — one large blockquote in Fraunces italic 500, 32px, with attribution.
8. **Pricing** — 3 columns. Free · Pro (₹299/mo) · Enterprise. Middle column has emerald ring emphasis.
9. **Final CTA band** — full-width, dark gradient (obsidian → slightly lighter), massive Fraunces "Start understanding your spending in 5 minutes" with primary button below.
10. **Footer** — 4 columns of links + copyright.

Every section fades + slides up 12px on entering viewport, staggered per child, using Framer's `whileInView`.

### 5.2 Login (`/login`)

Split panel. Left 55%: obsidian background, ambient emerald blob, huge Fraunces "Vitta" wordmark, tagline in `--ink-secondary`. Right 45%: elevated surface, centered form. "Welcome back" heading. Single "Continue with Google" button (48px, emerald, with Google logo). Tiny caption below with legal links.

### 5.3 Sales (`/sales`)

Two-column form. Left: value prop copy — Fraunces heading + Inter body. Right: form card. Fields: Full name, Work email, Company, Team size (segmented control 1-10 / 11-50 / 51-200 / 201+), Use case (textarea, 3 rows). Submit → success state with animated emerald checkmark (SVG stroke draw).

### 5.4 App shell

Fixed left sidebar 240px wide, `--bg-elevated`. Logo + wordmark at top. Nav items with Lucide icons: LayoutDashboard (Overview), Receipt (Transactions), Grid3X3 (Categories), Store (Merchants), CreditCard (Accounts), Sparkles (Insights), Settings (Settings). Active item: 2px emerald left border + emerald ink + subtle emerald wash background.

Top bar 64px: global search (Cmd+K), theme toggle, "Upload statement" primary button, avatar dropdown.

### 5.5 Overview (`/app`)

Grid layout:
1. **Greeting**: Fraunces 32px "Good morning, Varun." Below in `--ink-muted`: "Here's what happened across your accounts."
2. **Stat tile row** — 4 cards. Label (mono-label caps), value (JBMono 32px animated count-up), delta below (arrow + %, emerald if good direction, coral if not). Hover: border brightens.
3. **Trend chart** — full-width card, 320px tall. Area chart, 6 months of spending. SVG path draws in on mount. Y-axis in JBMono, X-axis month labels in Inter. 6M / 1Y / All segmented control top-right.
4. **Two-column** — Category breakdown (horizontal stacked bar chart with legend below) + Top 10 merchants (vertical bar chart, bars grow on mount with stagger).
5. **Recurring subscriptions callout** — full-width emerald-wash card with SparklesIcon, headline "You're paying ₹4,247/month across 6 subscriptions.", list of 3 items with "See all" link.
6. **Recent transactions** — table of last 8, click a row → slide-over drawer.

### 5.6 Transactions (`/app/transactions`)

Sticky filter bar: search input (with Cmd+K binding), category multi-select chips, account filter, date range picker with presets, source filter, "Add rule" button.

Table below. Columns: Date (JBMono) · Merchant (raw + source badge) · Category (colored pill, click to change inline via popover) · Account · Amount (JBMono, tabular, colored by direction). Row hover: subtle wash. Row click: slides open a right drawer with full detail (VPA, UPI ref, remark, dedup group, raw statement line).

Bulk-select checkbox column. When 1+ selected: floating action bar slides in from bottom with bulk actions.

### 5.7 Categories (`/app/categories`)

Grid of category cards. Each card: 4px colored top border (category color from data-viz palette), Fraunces heading (category name), Inter 500 label ("Spent this month"), JBMono value, mini sparkline in category color, tiny stats row (transaction count, % of total). Click a card → drilldown page.

### 5.8 Merchants (`/app/merchants`)

The tag-once dictionary. Search bar top. Table: Merchant (raw name) · VPA (mono, small, muted) · Applied to (n transactions) · Category (inline-editable dropdown) · Actions. Edit propagates. Bulk edit as in Transactions.

### 5.9 Accounts (`/app/accounts`)

Grid of account cards. Each card: bank name + last-4, holder, account type badge, total transactions, last sync, "Upload new" button. Click a card → drilldown. Add-account button opens the upload flow modal.

**Upload flow** (global modal):
- Drag-drop zone (dashed emerald border, brightens on drag-over). Multi-file support.
- Detected format shows as chip.
- Password field appears only if PDF is encrypted.
- Parse progress: streaming preview shows detected account → transactions found → duplicates removed → categorized (each with a checkmark that animates in).
- Post-parse review: summary card ("Detected 2 accounts, 87 transactions, 62% auto-categorized"). Review table shows first 10 rows. "Import" (primary emerald) or "Cancel".

### 5.10 Insights (`/app/insights`)

Two-panel layout. Left 60%: insight feed. Each insight card has: sparkles icon (violet wash), Fraunces heading, Inter body, action link. Cards fade in staggered as they load. Right 40%: chat with Vitta AI. Message history + input at bottom. Empty state: violet-tinged illustration + suggestion chips ("How much did I spend on food last quarter?", etc.). Streaming responses render token-by-token.

### 5.11 Settings (`/app/settings`)

Tabbed. Profile · Data & Privacy · Notifications · Integrations · Danger zone. Danger zone tab has red accent border, contains "Delete a statement", "Export all data", "Delete account" — each with confirm modal requiring typing "DELETE".

---

## 6. Data model (Supabase / Postgres)

```sql
-- accounts
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

-- transactions
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

-- merchant dictionary (tag-once rules)
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

-- contact map (Phase 1: CSV upload from Google Contacts)
CREATE TABLE contact_map (
  user_id uuid REFERENCES auth.users,
  phone text,
  contact_name text NOT NULL,
  PRIMARY KEY (user_id, phone)
);

-- upload jobs
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

-- sales leads
CREATE TABLE sales_leads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name text, work_email text, company text,
  team_size text, use_case text,
  created_at timestamptz DEFAULT now()
);

-- RLS on every table
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own rows" ON accounts USING (auth.uid() = user_id);
-- (same for transactions, merchant_dictionary, contact_map, upload_jobs)
```

---

## 7. PDF parsing (FastAPI, in `/backend`)

Endpoint: `POST /api/parse` — accepts file + `source` type. Returns normalized JSON.

Parsers required:

- **GPay PDF** — regex on lines like `Paid to X · UPI Transaction ID: NNN · Paid by [Bank]`. Simple.
- **PhonePe PDF** — similar structure.
- **Indian bank PDF** — narration format like `HDFC0004699/P SHREYAS GOWDA/XXXXX43681/6361943681-3@axl/UPI/621641459779/mane`. Regex-extract: IFSC prefix, payee name, masked account, VPA, UPI ref (12 digits), remark (last token after `/`). Handle password decrypt via `pypdf.PdfReader(...).decrypt()`.
- **Credit card PDF** — per-bank templates. Extract MCC when present.

Output shape:
```json
{
  "account": { "bank": "Indian Bank", "last4": "7318", "ifsc": "IDIB000A682" },
  "transactions": [{
    "date": "2026-08-04",
    "amount": 10000,
    "direction": "debit",
    "merchant_raw": "P SHREYAS GOWDA",
    "vpa": "6361943681-3@axl",
    "upi_ref": "621641459779",
    "remark": "mane"
  }]
}
```

---

## 8. Categorization — 3 tiers, cascading

For each new transaction, evaluate in order. Stop when a tier matches.

**Tier 1 — Rules (deterministic):**
1. Match on VPA pattern (`zeptoonline@ybl` → Groceries, `swiggy.payu@*` → Groceries, `*.rzp@rxaxis` → merchant Razorpay-hosted).
2. Match on merchant name keywords (contains "swiggy" / "flipkart" / "blinkit" / etc.).
3. Match on remark keyword ("pizza" → Food, "rapido"/"uber"/"ola" → Transport, "rent" → Housing).
4. Match on MCC (credit card only — MCC 5411 → Groceries, 5812 → Restaurants).

Ship with a JSON file `data/categories.ts` containing ~200 merchant rules + ~50 remark keywords.

**Tier 2 — User merchant dictionary:**
- Tagged merchants (stored in `merchant_dictionary`) auto-apply to all past + future transactions.
- If VPA contains a phone number that matches `contact_map`, use the saved contact name as `merchant_clean`.

**Tier 3 — LLM suggestion (only when Tiers 1 & 2 miss):**
- Send Groq LLM: merchant name, amount, time-of-day, day-of-week, count of past payments to same name.
- LLM returns `{ category, confidence }`.
- Confidence ≥ 0.7 → apply automatically (marked "AI-tagged").
- Below 0.7 → leave uncategorized, surface in Insights.
- User confirms → becomes a Tier 2 rule.

**Self-transfer detection:**
- Two transactions on user-owned accounts, same amount, within 48h, opposite directions → both flagged `is_self_transfer = true`.
- Payments TO user's own VPAs → same flag.
- Self-transfers excluded from all totals.

**Dedup:**
- Same UPI ref across sources → grouped under one `dedup_group_id`.
- Fallback: match on (amount, date ± 1, direction, merchant fuzzy match ≥ 80%).
- Bank row keeps VPA + remark; GPay row keeps merchant name. Merged into one canonical.

---

## 9. AI (Groq API, free tier)

Model: `llama-3.3-70b-versatile`. Env: `GROQ_API_KEY`.

Three uses:

**A. Category suggestion** (Tier 3 above).

**B. Insights feed** — nightly job scans user data, produces 3–5 cards:
- Recurring subscriptions
- Anomalies ("Food spend up 40% vs 3-month average")
- Category shifts
- Savings opportunities (unused subscriptions)

Prompt:
```
You are Vitta, a financial coach. Given this user's transaction summary,
generate 3-5 short insight cards. Each: one-sentence observation + one-sentence
actionable suggestion. Never invent numbers — use only what's provided.
Data: {json_summary}
Output JSON: [{ "title": "", "body": "", "action": "" }]
```

**C. Ask anything (text-to-SQL):**
Two-step. LLM produces SQL against a read-only view, backend executes, LLM narrates result.

```
System: You are a SQL analyst for Vitta. Only SELECT queries against the
`transactions_view` for user_id = '{uid}'. Schema: {schema}.
User asks in natural language. Return only SQL, no prose.

Assistant response is validated: must be SELECT, must reference `transactions_view`,
must have `user_id = '{uid}'` in WHERE. Backend runs it with a role that has SELECT
only on that view. Result rows returned to a second LLM call to narrate.
```

**The LLM never does arithmetic itself.** This is non-negotiable.

---

## 10. Security defaults

- RLS on every table.
- Source PDFs deleted from Storage after successful parse. Keep normalized rows only.
- HTTPS everywhere.
- No third-party analytics that see transaction content (PostHog self-hosted is OK).
- Rate limit LLM endpoints per user.
- DPDP-compliant "delete my data" cascade.

---

## 11. MVP scope — do these in order, don't skip ahead

1. **Design tokens + Logo component + Button + Card + basic layout primitives.** Build a `/dev` route that shows every component.
2. **Landing page.** Static, with real copy and the July 2026 dashboard preview inline.
3. **Login (Google OAuth via Supabase).**
4. **App shell** (sidebar + top bar + empty routes).
5. **Overview screen with seed data.** All charts working, animations wired.
6. **Transactions table with seed data.**
7. **Upload flow modal (mocked parse — backend later).**
8. **Categories + Merchants + Accounts screens.**
9. **Insights screen with mocked AI responses.**
10. **Backend FastAPI service — GPay parser first.**
11. **Wire real parse endpoint. Then bank statement parser.**
12. **Wire LLM (Groq) for Tier 3 categorization + insights + chat.**
13. **Sales page + Talk to Sales form → Supabase leads table.**
14. **Settings + Danger zone + data export/delete.**

Each step must render correctly on both dark (primary) and light. Every animation must respect `prefers-reduced-motion`.

---

## 12. Seed data for the demo

Include `src/data/seed.ts` with the July 2026 transactions from the real GPay statement (Varun's data). Every stat, chart, and table on the Overview screen should populate from this seed so the UI is testable before the backend is wired.

Sample structure:
```ts
export const seedTransactions = [
  { date: '2026-07-03', merchant: 'SWIGGY INSTAMART', vpa: 'swiggy.payu@axisb',
    amount: 150, direction: 'debit', category: 'Groceries',
    source: 'gpay_pdf', upi_ref: '618483978561' },
  // ... 80+ more from the real statement
];
```

---

## 13. What "done" looks like for MVP

- Landing loads under 1s, Lighthouse ≥ 90.
- User signs in with Google in one click.
- Upload a real GPay PDF, get a working dashboard within 30 seconds.
- Every chart animates in. Every stat counts up. Every hover state has a purpose.
- Ask "how much did I spend on food last month" and get a correct number.
- Dark mode is beautiful; light mode also works but is secondary.
- No screen anywhere looks like Slack, Notion, or any generic SaaS template.

---

**Start with Step 1 (design tokens + Logo + primitives). Show me the `/dev` component gallery before moving to the landing page.**
