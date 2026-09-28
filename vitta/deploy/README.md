# Deploying Vitta for $0/month

The stack — all free forever, no card required:

| Piece      | Provider                     | What it costs        |
| ---------- | ---------------------------- | -------------------- |
| Frontend   | **Cloudflare Pages**         | Free, unlimited      |
| Backend    | **Render.com** free web service | Free, sleeps after 15 min idle (~30s cold start) |
| Database   | **SQLite** (built-in), or **Turso** for persistence | Free |

**Trade-off you should know:** Render's free-tier disk is **ephemeral** — every redeploy wipes the SQLite file. For a demo that's fine. For real users, use Turso (step 4 below) — it takes ~30 minutes and is also free.

Total time end-to-end: **~1 hour.**

---

## 1 · Push to GitHub (5 min)

If you haven't already:

```bash
cd /Users/vas-contractor/SRET
git status                    # make sure everything's committed
git push
```

The `phase2/open-signup` branch on `varunSbabu/vitta-finance` is what gets deployed.

---

## 2 · Frontend on Cloudflare Pages (10 min)

1. Go to https://dash.cloudflare.com → **Workers & Pages** → **Create application** → **Pages** → **Connect to Git**.
2. Authorize GitHub and pick `varunSbabu/vitta-finance`.
3. Setup:
   - Project name: `vitta`
   - Production branch: `phase2/open-signup`
   - Framework preset: **None**
   - Build command: *(leave empty)*
   - Build output directory: `vitta`
4. Click **Save and Deploy**. First deploy takes ~2 minutes.
5. You get a URL like `https://vitta.pages.dev`.

Visit `https://vitta.pages.dev/app.html` — the landing page loads. The app will fail to log in yet because the API base is empty; we fix that after the backend is up.

### 2 (alternative) · Frontend on Vercel

Use this instead of Cloudflare Pages if you prefer Vercel.

1. Go to https://vercel.com/new and sign in with GitHub.
2. Import `varunSbabu/vitta-finance`.
3. Configure:
   - Framework Preset: **Other**
   - Root Directory: `vitta` (click **Edit** to change it)
   - Build Command: leave empty (turn the override on and clear it if Vercel fills one in)
   - Output Directory: leave empty
4. Click **Deploy**. You get a URL like `https://vitta-finance.vercel.app`.

`vitta/.vercelignore` limits the upload to `app.html`, `config.js` and `vitta-mark.svg`, so backend code and docs are never public. `vitta/vercel.json` serves `app.html` at `/` and turns off caching for `config.js`, so changing the API URL takes effect on the next load.

Production branch: Vercel deploys the repo's default branch (`main`) to production. Until this work is merged to `main`, either merge first, or set Settings → Git → Production Branch to `phase2/open-signup`.

Wherever the rest of this guide says `https://vitta.pages.dev`, use your Vercel URL instead: in Render's `FRONTEND_URL` and `ALLOWED_ORIGINS`, and in Google's Authorized JavaScript origins.

---

## 3 · Backend on Render (20 min)

1. Go to https://render.com → **New +** → **Blueprint**.
2. Connect the same GitHub repo. Render finds `vitta/render.yaml` and lists the `vitta-api` service.
3. Click **Apply**. Build takes ~4 minutes.
4. You get a URL like `https://vitta-api.onrender.com`.
5. In the Render dashboard for `vitta-api` → **Environment** → add these secrets:
   ```
   SESSION_SECRET_KEY   = python3 -c "import secrets; print(secrets.token_hex(32))" → paste the output
   GOOGLE_CLIENT_ID     = from Google Cloud Console
   GOOGLE_CLIENT_SECRET = from Google Cloud Console
   GROQ_API_KEY         = from https://console.groq.com/keys
   ADMIN_EMAIL          = your admin email (e.g. varunbabu098@gmail.com)
   VITTA_ENV            = prod
   ```
6. Update the two URL env vars already in `render.yaml` to match your actual Pages URL:
   ```
   FRONTEND_URL     = https://vitta.pages.dev/app.html#/app
   ALLOWED_ORIGINS  = https://vitta.pages.dev
   ```
7. Click **Manual Deploy → Deploy latest commit** so the new env vars take effect.
8. Test: `curl https://vitta-api.onrender.com/api/health` → `{"status":"ok"}`.

---

## 4 · Point the frontend at the backend

Edit `vitta/config.js`:

```js
window.VITTA_API_BASE = window.VITTA_API_BASE || "https://vitta-api.onrender.com";
```

Commit + push. Cloudflare Pages auto-redeploys in ~30 seconds.

---

## 5 · Update Google OAuth redirect URI

In [Google Cloud Console → APIs & Services → Credentials → your OAuth client](https://console.cloud.google.com/apis/credentials):

**Authorized redirect URIs → add:**
```
https://vitta-api.onrender.com/api/auth/callback
```

**Authorized JavaScript origins → add:**
```
https://vitta.pages.dev
```

Save. Wait ~1 minute for Google to propagate.

---

## 6 · Test the end-to-end flow

1. Open `https://vitta.pages.dev/app.html`.
2. Click **Get started** → sign in with Google.
3. First click after Render's nap takes ~30s (cold start); after that it's fast.
4. Upload a statement. Visit `#/app/admin` (only your admin email sees it).

If the login redirects but you land back on the landing page, check the browser console. Common causes:
- `ALLOWED_ORIGINS` doesn't include the exact Pages URL (no trailing slash).
- `VITTA_ENV=prod` isn't set, so the session cookie is still SameSite=Lax and the browser drops it.
- Google redirect URI mismatch (must be exactly `https://<render-url>/api/auth/callback`).

---

## 7 · Optional: persistent DB via Turso (30 min)

Render free tier's disk resets on every redeploy, so your data disappears. **Turso** is a managed SQLite hosted in the cloud — free tier is 9 GB / 1 billion rows-read per month, way more than you'll ever use.

### 7a · Provision Turso

```bash
# On your Mac, install the Turso CLI:
brew install tursodatabase/tap/turso
turso auth signup             # or `turso auth login` if you have an account

turso db create vitta         # creates the DB
turso db show vitta --url     # copy this — it's TURSO_DATABASE_URL
turso db tokens create vitta  # copy this — it's TURSO_AUTH_TOKEN
```

### 7b · Add the dependency

Edit `vitta/backend/pyproject.toml` and add to `dependencies`:
```
"libsql-experimental==0.0.55",
```

### 7c · Update `vitta/backend/db.py`

Replace the `get_conn()` function so it uses libsql when `TURSO_DATABASE_URL` is set, and stays on local `sqlite3` otherwise. The rest of the codebase already uses `conn.execute` / `conn.commit` / `conn.close` which libsql supports. See the "Turso migration" section further down for the exact patch.

### 7d · Set the env vars on Render

In Render dashboard → Environment → add:
```
TURSO_DATABASE_URL = libsql://vitta-<yourorg>.turso.io
TURSO_AUTH_TOKEN   = <the token from step 7a>
```

Redeploy. Every user, transaction, and contact now persists across redeploys.

---

## 8 · Ongoing care

- **Custom domain (optional):** Cloudflare Pages → Custom domains → add `vitta.yourdomain.com`. Free.
- **Backups (if using Turso):** Turso keeps 3 daily backups on the free tier automatically.
- **Backups (if not using Turso):** `curl -o vitta-$(date +%F).db https://vitta-api.onrender.com/api/admin/export-db` — but you'll need to build that endpoint first.
- **Rotate keys:** you already know your `SESSION_SECRET_KEY` and `GROQ_API_KEY` were exposed. Generate new ones for production and don't commit `.env`.

---

## Rollback

- **Frontend:** Cloudflare Pages keeps every deploy → **Deployments** tab → click any prior deploy → **Rollback**.
- **Backend:** Render → your service → **Deploys** → click any prior deploy → **Rollback**.
- **Turso:** `turso db shell vitta` and restore from a `.dump` backup.

---

## Cost review

| Piece | Free tier limit | Vitta reality |
| --- | --- | --- |
| Cloudflare Pages | Unlimited requests + bandwidth | Nowhere near |
| Render web service | 750 hrs/mo | Sleeps when idle, comfortably free |
| Turso | 9 GB storage, 1B row reads/mo | You'll use <1% of this |

You will not pay a rupee unless you outgrow the free tiers, which won't happen at the 10-100 user scale.
