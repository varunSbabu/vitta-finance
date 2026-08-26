# Vitta — Complete Build Brief

Build a production-grade expense analytics web application for the Indian market. It ingests statements from any Indian bank, UPI app, or credit card and turns raw transactions into an intelligent, categorized, AI-narrated view of the user's financial life.

---

## 1. Product positioning

**Vitta** (Sanskrit: वित्त — finance, wealth). Working name — treat as final. Tagline: **"Every rupee, understood."**

Serves two audiences from a single product surface:
- **Personal users** — sign up self-serve, upload their own statements, get categorization + insights
- **Small businesses / freelancers / proprietors** — same product, plus multi-account handling, GST-aware categorization, and a "Talk to Sales" enterprise path

The core wedge: no Indian expense app today parses **multi-source Indian statements** (bank + GPay + PhonePe + credit card) with real AI-powered categorization for consumers. Walnut is dead, Fi/Jupiter only work with their own bank accounts, and the B2B players (Perfios, Finbox) don't sell to individuals. That is the gap.

---

## 2. Tech stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | **React + Vite** with TypeScript, Tailwind CSS, Framer Motion for animations | Fast, standard, animation-rich |
| Backend | **Python FastAPI** | Owns PDF parsing where the ecosystem is strongest |
| Database | **PostgreSQL** (via Supabase for MVP) | Relational is right for this data |
| File storage | **Cloudflare R2** or Supabase Storage | Encrypted at rest, cheap |
| Auth | **Supabase Auth** with Google OAuth | Zero-effort Google login |
| PDF parsing | `pdfplumber`, `pypdf` (for password decrypt), `camelot-py` (for tabular bank statements) | Battle-tested Indian bank statement parsing |
| Charts | **Recharts** for standard, **D3** for custom viz | Recharts covers 90% |
| Animation | **Framer Motion** | Page transitions, chart entry, hover micro-interactions |
| LLM | **Groq API** (`llama-3.3-70b-versatile`, free tier) primary; **Google Gemini 1.5 Flash** (free tier) fallback | Both offer generous free tiers for coaching + suggestions |
| Deployment | **Vercel** (frontend) + **Railway/Render** (FastAPI service) + **Supabase** (DB + auth + storage) | Fast to ship |

Row-level security (RLS) on every Supabase table: `auth.uid() = user_id`. Enable before any real data goes in.

---

## 3. Design system — build from these tokens

### Color

```css
--brand: #611F69;              /* Deep aubergine — primary CTAs, nav */
--brand-600: #7A2A83;          /* Hover */
--brand-700: #4A154B;          /* Active */
--brand-wash: rgba(97,31,105,0.06);      /* Subtle wash / focus ring */
--brand-wash-strong: rgba(97,31,105,0.12);

/* Neutrals — light */
--bg: #F8F8F8;
--bg-elevated: #FFFFFF;
--bg-subtle: #F1F1F1;
--border: #E8E8E8;
--border-strong: #D6D6D6;
--ink: #1D1C1D;
--ink-secondary: #454347;
--ink-muted: #616061;

/* Semantic */
--success: #007A5A;
--warning: #B45300;
--danger:  #C1121C;
--info:    #1264A3;

/* Neutrals — dark (invert brand to soft lilac for legibility) */
--brand-dark: #D4A8DC;
--bg-dark: #1A1D21;
--bg-elevated-dark: #222529;
--ink-dark: #E8E8E8;
```

### Chart palette (CVD-validated, use in fixed order — never cycle)

```
Slot 1 blue    #2A78D6
Slot 2 orange  #EB6834
Slot 3 aqua    #1BAF7A
Slot 4 yellow  #EDA100
Slot 5 magenta #E87BA4
Slot 6 green   #008300
Slot 7 violet  #4A3AA7
Slot 8 red     #E34948
```

Sequential (heatmaps, ramps): blue `#CDE2FB → #0D366B`. Diverging (deltas): blue ↔ red with gray `#F0EFEC` midpoint.

### Typography (Slack's public typeface — Lato only)

Load once:
```html
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Lato:wght@400;700;900&family=JetBrains+Mono:wght@400;500&display=swap">
```

- **Lato** for everything — display, headings, and body. Weights: **400 regular, 700 bold, 900 black.** No 500/600/800 — Lato doesn't have them, and Slack itself uses only these three.
- **JetBrains Mono** for numbers where digits align (tables, tick labels, stat tile values in columns). Use `font-variant-numeric: tabular-nums`.
- Type scale: hero 88/900 · display 48/900 · section-head 28/900 · card-head 22/700 · body-lg 17/400 · body 15/400 · caption 11/700 uppercase (mono).
- Letter-spacing tighter as size grows: `-0.045em` on hero, `-0.02em` on display, `-0.01em` on headings.

### Shape & rhythm

- Radius: **4** chips, **6** buttons, **8** inputs, **12** cards, **16** modals, **9999** pills.
- Spacing on a **4px grid**: 4, 8, 12, 16, 24, 32, 48, 64.
- Elevation is minimal — `0 1px 2px rgba(29,28,29,0.04)` for cards, `0 4px 10px rgba(29,28,29,0.06)` for modals. No neon glows.

### Logo — stacked bars monogram

Four ascending vertical bars, all in shades of aubergine (light lilac → deep aubergine). Widths uniform, heights `42% · 62% · 82% · 100%`, gap `8px`. Reads as a tiny bar chart AND hints at the letter V. Same shape used at:
- 12px (top strip / favicon) — solid white on aubergine ground
- 24px (product nav)
- 96px (hero mark) — color gradient on white card

### Motion

Every animation is subtle and functional — never decorative. Use **Framer Motion**.

- **Page transitions**: fade + 8px slide-up on route change, 240ms ease-out
- **Stat tile numbers**: `useSpring` to animate value from 0 → target on mount, 800ms
- **Bar chart entry**: bars grow from 0 width, staggered 40ms per row, 400ms each
- **Hover on rows**: background wash fades in over 120ms
- **Skeletons** on data refetch: hold previous render at 40% opacity, no layout jump
- **Toast**: slide in from bottom-right, 200ms, auto-dismiss 4s
- Respect `prefers-reduced-motion` — reduce all durations to `0.01ms` (effectively off)

---

## 4. Information architecture

### Public (unauthenticated)

| Route | Purpose |
|---|---|
| `/` | Landing page |
| `/security` | How we handle statement data |
| `/pricing` | Free / Pro / Enterprise plans |
| `/sales` | Talk to Sales form for enterprise |
| `/login` | Google OAuth |

### App (authenticated, behind sidebar shell)

| Route | Purpose |
|---|---|
| `/app` | Dashboard overview |
| `/app/transactions` | Full transaction table |
| `/app/categories` | Category drill-downs |
| `/app/merchants` | Merchant dictionary + tag-once |
| `/app/accounts` | Connected accounts + upload |
| `/app/insights` | AI chat + auto-generated insights |
| `/app/settings` | Profile, data controls, integrations |

---

## 5. Screen-by-screen specs

### 5.1 Landing page (`/`)

Editorial marketing page. Sections top-to-bottom:

1. **Nav bar** — sticky, off-white translucent. Left: stacked-bars logo + "Vitta" wordmark. Right: Product · Pricing · Security · Sign in (ghost) · Get started free (primary aubergine button).
2. **Hero** — 88px Lato Black headline "Every rupee, understood." Subhead 22px Lato Regular: "Vitta reads your bank statements, UPI apps, and credit cards — and turns them into a picture you can actually act on." Two CTAs: Primary "Get started free" + Secondary "Talk to sales". Right side: product screenshot of the dashboard overview (use the built dashboard as the reference image).
3. **The problem strip** — three big numbers side by side, animated to count up on scroll into view: `35%` (auto-categorized by name alone), `~25 unique payees per user`, `95%` (bank statement coverage). Caption under each explains what it means.
4. **How it works** — 3-step horizontal flow with icons: Upload → Parse → Understand. Each step 240px wide with a Lottie or Framer illustration.
5. **Feature grid** — 6 cards, 3×2. Titles: Multi-source ingest · Tag once, remember forever · Ask anything (AI Q&A) · Recurring detection · Multi-account · Bank-grade security. Each card 20px feature icon (aubergine wash background), heading, 2-line description.
6. **Trust section** — "Your data, handled with care." Bullets: source files deleted after parsing · encrypted at rest · DPDP-compliant · never resold. Aubergine badge row: SOC 2 (soon), DPDP-ready, Encrypted at rest.
7. **Testimonials** — placeholder cards (fill in later).
8. **Pricing** — 3 columns. **Free** (personal, 3 accounts, 6 months history) · **Pro** ₹299/mo (unlimited accounts, unlimited history, AI insights) · **Enterprise** ("Talk to Sales" button — no price shown).
9. **Final CTA** — full-width aubergine band with "Start understanding your spending in 5 minutes" and a big white button.
10. **Footer** — 4 columns: Product · Company · Legal · Contact.

Every section on scroll fades + slides up 16px, staggered 80ms.

### 5.2 Login (`/login`)

Split screen. Left 50%: aubergine ground, big Lato Black "Vitta" wordmark, tagline in white 70% opacity. Right 50%: white, centered form. "Sign in to Vitta" heading. "Continue with Google" button (Google logo + Lato bold text). Small caption: "By continuing you agree to our Terms and Privacy." No email/password — Google OAuth only for MVP.

### 5.3 Talk to Sales (`/sales`)

Two-column form. Left: value prop copy. Right: form fields — Full name, Work email, Company, Team size (dropdown: 1-10 / 11-50 / 51-200 / 201+), Use case (multiline). Submit sends to Supabase table + webhook to Slack/email. Success state: aubergine checkmark animation, "We'll be in touch within 1 business day."

### 5.4 Dashboard overview (`/app`)

Layout: fixed left sidebar (dark aubergine `#4A154B` ground, white text, 240px wide) + top bar (white, search + upload button + avatar) + main content area.

**Sidebar sections** with icon + label:
- Overview · Transactions · Categories · Merchants · Accounts · Insights · Settings

**Main content**:
1. **Greeting row** — "Good morning, Varun." + last-synced pill.
2. **Stat tile row** (4 tiles): Total spent this month · Total received · Auto-categorized % · Recurring monthly. Each tile: label (11px mono caps), value (32px Lato Black, animated count-up), delta (up/down colored). Values from real DB.
3. **Trend chart** — 6-month spending trend, area chart with the sequential blue ramp fill, aubergine 2px stroke on top. Framer entry: stroke draws left-to-right over 800ms, fill fades in after.
4. **Two-column row**:
   - Left: **Category breakdown** — horizontal stacked bar showing spend split, with legend below. Uses chart palette slots 1-8 in fixed order. Hover a segment → tooltip with amount + %.
   - Right: **Top 10 merchants** — vertical bar chart, bars animate in staggered.
5. **Recurring subscriptions callout** — full-width card, purple wash background, lists detected recurring payments. "You're paying ₹2,047/month across 6 subscriptions."
6. **Recent transactions** — last 8 rows, click through to full table.

### 5.5 Transactions (`/app/transactions`)

Full-width table. Sticky filter bar at top: search input, category multi-select, account filter, date range picker (with presets: today, 7d, 30d, 90d, MTD, custom), source filter (Bank / GPay / PhonePe / Credit card).

Table columns: Date · Merchant (with source badge) · Category (colored pill, click to change inline) · Account · Amount (mono, tabular). Right-click or 3-dot menu on any row: Re-categorize · Tag merchant · Mark as self-transfer · Split. Bulk select checkbox on left → floating toolbar appears with bulk actions.

Row hover: aubergine wash background. Row click: opens right-slide drawer with full transaction detail (VPA, UPI ref, remark, dedup group).

### 5.6 Categories (`/app/categories`)

Grid of category cards. Each card: category color stripe on left, name, total spent, % of total, sparkline trend. Click a card → drilldown page: all transactions in this category, merchants in this category ranked, month-over-month trend, largest transactions.

### 5.7 Merchants (`/app/merchants`)

The tag-once dictionary UI. Table: Merchant name (raw, from statement) · Category (dropdown, editable inline) · Rule scope (VPA or name-based) · Applied to (transaction count) · Actions. Editing a row auto-applies to every past + future transaction. Bulk edit: select N rows → assign single category.

### 5.8 Accounts (`/app/accounts`)

List of connected accounts. Each account card: bank name + logo, last 4 digits, account holder name, VPAs associated, total transactions parsed, last upload date, "Upload new statement" button. Delete button (with confirm modal — this wipes all transactions from this account irreversibly).

**Upload flow** (opens as modal from any screen's upload button):
- Drag-drop area or click-to-browse. Multi-file supported.
- File format auto-detected: GPay export, PhonePe export, bank statement (per-bank template), credit card.
- If password-protected: prompt with hint "Try DDMMYYYY of your DOB" (bank convention).
- Parse in-progress: streaming preview shows what's been extracted (account detected → transactions found → duplicates removed → categorized).
- Post-parse review: "Detected 2 accounts, 87 transactions, 62% auto-categorized. Review before importing?" User can edit before commit.

### 5.9 Insights (`/app/insights`)

Two-panel layout. Left: auto-generated insight feed (LLM-produced cards summarizing patterns — see AI section). Right: chat with Vitta AI. Chat box at bottom, message history above. Example prompts shown as chips: "How much did I spend on food last quarter?" · "What subscriptions am I paying for?" · "Am I saving more or less than last month?"

The LLM never does math — it produces a SQL query, backend runs it, LLM narrates the result.

### 5.10 Settings (`/app/settings`)

Tabs: Profile · Data & Privacy · Notifications · Integrations · Danger zone.

**Data & Privacy** is the important one: "Delete a specific statement", "Delete all data", "Export all data as CSV/JSON". Contacts CSV upload lives here too (Google Contacts export → uploaded → phone-to-name mapping stored to enrich person-name categorization).

---

## 6. Data model (PostgreSQL / Supabase)

```sql
-- users: managed by Supabase Auth

CREATE TABLE accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users NOT NULL,
  bank_name text NOT NULL,
  account_last4 text NOT NULL,
  account_holder text,
  ifsc text,
  account_type text,  -- savings, current, credit_card
  vpas text[] DEFAULT '{}',  -- user's own VPAs for self-transfer detection
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
  merchant_raw text NOT NULL,        -- as it appears in statement
  merchant_clean text,               -- resolved friendly name
  vpa text,                          -- extracted from bank narration
  remark text,                       -- user-typed UPI note
  upi_ref text,                      -- primary dedup key
  source text NOT NULL,              -- gpay_pdf, bank_pdf, phonepe_pdf, cc_pdf
  category text,
  is_self_transfer boolean DEFAULT false,
  is_recurring boolean DEFAULT false,
  dedup_group_id uuid,               -- links same txn across sources
  mcc text,                          -- credit card MCC when available
  raw_json jsonb,                    -- everything the parser extracted
  created_at timestamptz DEFAULT now()
);

CREATE INDEX ON transactions (user_id, txn_date DESC);
CREATE INDEX ON transactions (user_id, category);
CREATE INDEX ON transactions (upi_ref);

CREATE TABLE merchant_dictionary (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users NOT NULL,
  merchant_key text NOT NULL,        -- normalized name or VPA
  match_type text CHECK (match_type IN ('exact_name','vpa','name_contains')),
  display_name text,
  category text NOT NULL,
  is_user_tagged boolean DEFAULT true,
  applied_count int DEFAULT 0,
  UNIQUE(user_id, merchant_key, match_type)
);

CREATE TABLE upload_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES auth.users NOT NULL,
  file_name text NOT NULL,
  source text NOT NULL,
  status text NOT NULL,  -- queued, parsing, review, imported, failed
  parsed_summary jsonb,
  error text,
  created_at timestamptz DEFAULT now()
);

CREATE TABLE contact_map (
  user_id uuid REFERENCES auth.users NOT NULL,
  phone text NOT NULL,
  contact_name text NOT NULL,
  PRIMARY KEY(user_id, phone)
);

CREATE TABLE sales_leads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  full_name text, work_email text, company text,
  team_size text, use_case text,
  created_at timestamptz DEFAULT now()
);

-- Enable RLS on every table:
-- ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "own rows" ON {table} USING (auth.uid() = user_id);
```

---

## 7. Ingestion pipeline (FastAPI service)

Endpoint: `POST /api/parse` — accepts a file + `source` type. Returns normalized JSON.

Parsers to implement:

- **GPay PDF** — structured format ("Paid to X · UPI Transaction ID: NNN · Paid by [Bank]"). Simple regex parser.
- **PhonePe PDF** — similar structured format.
- **Indian bank PDF** — has narration lines like `HDFC0004699/P SHREYAS GOWDA/XXXXX43681/6361943681-3@axl/UPI/621641459779/mane`. Regex-extract: IFSC prefix, payee name, VPA, UPI ref, remark (last `/`-delimited token). Handle password decryption via `pypdf.decrypt()`.
- **Credit card PDF** — per-bank templates. Extract MCC codes when present.

Common output shape:
```json
{
  "account": { "bank": "Indian Bank", "last4": "7318", "ifsc": "IDIB000A682" },
  "transactions": [
    { "date": "2026-08-04", "amount": 10000, "direction": "debit",
      "merchant_raw": "P SHREYAS GOWDA", "vpa": "6361943681-3@axl",
      "upi_ref": "621641459779", "remark": "mane" }
  ]
}
```

---

## 8. Categorization engine (3 tiers, cascading)

For each new transaction, in order:

**Tier 1 — Rules (deterministic, free, instant):**
1. Match on VPA pattern (e.g., `zeptoonline@ybl` → Groceries; `swiggy.payu@axisb` → Groceries).
2. Match on merchant name keywords (contains "swiggy" / "flipkart" / "blinkit" / etc.).
3. Match on remark keyword (e.g., remark `"pizza"` → Food, `"rapido"` → Transport, `"gym subscription"` → Health).
4. Match on MCC (credit card only).

Ship with ~200 seeded merchant rules and ~50 remark keywords in a JSON file the app can update.

**Tier 2 — User merchant dictionary:**
- Once user tags a merchant, insert into `merchant_dictionary`. All past + future transactions with that name/VPA auto-recategorize.
- Contact map: if payee VPA contains a phone number matching `contact_map`, use that contact's saved name as `merchant_clean`.

**Tier 3 — LLM suggestion (only when Tiers 1 & 2 miss):**
- Send to Groq LLM: merchant name, amount, time-of-day, day-of-week, frequency of past payments to same name.
- LLM returns a suggested category + confidence 0-1.
- If confidence ≥ 0.7: apply automatically as suggested (marked "AI-tagged" pill).
- Below 0.7: leave uncategorized, surface in review queue.
- User confirms/corrects → becomes a Tier 2 dictionary entry.

**Self-transfer detection:**
- If payment amount matches an incoming transaction on another user-owned account within 48h → mark both as `is_self_transfer = true`.
- Also match against user's own VPAs.
- Self-transfers excluded from spending totals and category breakdowns.

**Dedup:**
- Same UPI ref across two sources (bank + GPay) → group under one `dedup_group_id`.
- Fallback: match on (amount, date ± 1, direction, merchant fuzzy match).
- Bank statement version wins for VPA + remark; GPay version wins for clean merchant name.

---

## 9. AI integration (Groq API, free tier)

Model: `llama-3.3-70b-versatile` via Groq. Env var: `GROQ_API_KEY`. Fallback: Gemini 1.5 Flash via `GOOGLE_API_KEY`.

Three AI features:

**A. Category suggestion** (Tier 3 above).

**B. Insights feed** — nightly job scans user's data and generates 3–5 insight cards:
- Recurring subscription detection (with amount + cadence)
- Anomaly ("You spent 40% more on food this month than your 3-month average")
- Category shifts ("Groceries went down, restaurants went up — you're eating out more")
- Savings opportunities ("₹1,247/month across 3 apps that haven't been used")

Prompt template:
```
You are Vitta, a financial coach. Given the following user's transaction summary,
generate 3-5 short insight cards. Each card: one-sentence observation + one-sentence
actionable suggestion. Never invent numbers — use only the numbers provided.
Data: {json_summary}
```

**C. Ask anything (text-to-SQL chat):**

Two-step: LLM produces SQL → backend runs it → LLM narrates.

```
System: You are a SQL analyst for Vitta. Only produce read-only SELECT queries
against the transactions table for user_id = '{uid}'. Schema: {schema}.
Never do arithmetic — the SQL is the arithmetic.
User: How much did I spend on food last quarter?
Assistant: SELECT SUM(amount) FROM transactions WHERE user_id = '{uid}'
  AND category = 'Food' AND direction = 'debit'
  AND txn_date >= '2026-04-01' AND txn_date < '2026-07-01';
```

Backend executes with a read-only role, allow-lists the query (only SELECT, only against `transactions`, must have `user_id = '{uid}'` clause). Returns rows to LLM. LLM writes the human answer.

Never let the LLM do the math directly. This is the single most important design constraint.

---

## 10. Security & compliance (build in from day 1)

- Every DB row has `user_id`. RLS policies enforce isolation.
- Source PDFs deleted after successful parse — keep only normalized rows.
- Encryption at rest on file storage (R2 SSE or Supabase Storage default).
- HTTPS everywhere.
- DPDP-ready: user-facing "Delete my data" wipes user_id cascade.
- No third-party analytics that see transaction content.
- Rate-limit LLM endpoints per user (Groq free tier has token limits — cache aggressively).

---

## 11. Success criteria for the MVP

1. Upload GPay PDF + one bank statement PDF, parse both, dedup — one merged transaction feed
2. Auto-categorize ≥60% of transactions using Tier 1 rules on real Indian data
3. User can tag a merchant once and see it propagate to all past + future rows
4. Dashboard overview loads under 1s with real data
5. Ask "how much did I spend on X last month" and get a correct number-grounded answer
6. Landing page loads under 1s, Lighthouse ≥90 on Performance + Accessibility
7. Every screen renders correctly in both light and dark mode

---

## 12. What NOT to build in MVP

- SMS parsing (dead on Play Store, this is a webapp anyway)
- Account Aggregator / RBI-regulated integrations (requires being a licensed FIU)
- Gmail integration (requires CASA security review, months of process)
- Google Contacts OAuth integration (same restricted-scope problem — CSV upload only for Phase 1)
- Investment tracking, credit score, or lending features (scope creep)

---

Build it. Ship the landing page + login + upload + dashboard first. Everything else is Phase 2.
