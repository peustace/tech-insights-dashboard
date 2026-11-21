# Tech Insights Dashboard

A static dashboard for keeping up with fast-moving technology news. A scheduled GitHub Action reads
RSS feeds, asks Gemini for short summaries, ranks and de-duplicates the stories, and commits the result
as `data.json`. `index.html` renders it; there is no server and no build step.

## What you get

- **Top stories** ranked by importance, freshness and how many outlets cover them.
- **"Why it matters"** line, source name and publish time on every story.
- **Sectors:** AI, Semiconductors, Quantum, CyberSecurity, Space, Renewables, Energy, MedTech, Biotech,
  Telecommunications, Robotics, Policy, Funding & M&A, Developer Tools, plus a cross-sector **Breaking**
  feed (Techmeme, Hacker News).
- **Emerging now:** terms that suddenly appear across several independent sources (starts after 3 days of history).
- **Stock impact radar** and a **Sunday weekly recap**, both AI-written and labelled as such.
- **Browser features:** sector filter bar, search (press `/`), card or compact list view, light/dark/auto
  theme, pinned sectors, saved stories, "New since your last visit" badges, and a day-by-day archive picker.
  Preferences and saved stories live in your browser's local storage only.
- **Feed status** panel and warning banners, so a dead feed or failing AI step is visible rather than silent.
- Optional **Slack / email digest** of the top stories.

## How it works

```
sources.py ──► fetch_data.py ──► data.json            (what the page reads)
                  │          ├─► state/items.json     (cache: items are never summarised twice)
                  │          └─► archive/DATE.json    (daily snapshots + archive/index.json)
                  └─ insights.py  (cleaning, de-dupe, ranking, emerging terms; unit-tested)
digest.py ──► Slack / email
```

The workflow in `.github/workflows/daily_update.yml` runs every 4 hours (02, 06, 10, 14, 18, 22 UTC).
Items stay in the cache for 4 days, so quiet periods (for example arXiv on weekends) don't empty the page.
If every feed fails, the run exits with an error and leaves the previous `data.json` untouched.

## Setup

1. **Secrets** (Settings → Secrets and variables → Actions → *Secrets*):
   - `GEMINI_API_KEY` (required for AI summaries, stock radar and recap; without it the page falls back to feed text)
   - Optional digest: `SLACK_WEBHOOK_URL`, or `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `DIGEST_TO`, `DIGEST_FROM`
2. **Variables** (same page → *Variables*, all optional): `GEMINI_MODEL` (default `gemini-2.5-flash`),
   `SITE_URL` (link included in digests).
3. **Workflow permissions:** the workflow requests `contents: write` itself. If your organisation restricts the
   default token, allow read and write permissions under Settings → Actions → General.
4. **Publish the page** with GitHub Pages (Settings → Pages → deploy from the branch root).
5. **First run:** Actions → *Tech Insights Update* → *Run workflow*. Tick *Generate the weekly recap now* to try the recap.

## Customising

Edit `sources.py`. Each feed takes `name`, `url`, `type` (`news`, `paper`, `podcast`, `community`),
`weight` (ranking multiplier) and `limit` (entries per run). `PRIORITY_SECTORS` sets which sectors start pinned.
Feed URLs are not checked at build time; the *Feed status* panel shows any that return nothing.

## Run locally

```bash
pip install -r requirements.txt
GEMINI_API_KEY=your-key python fetch_data.py          # add --dry-run to avoid writing files, --no-ai to skip Gemini
python -m http.server 8000                              # then open http://localhost:8000
python digest.py --dry-run                              # preview the digest
python -m unittest discover -s tests -t .               # tests need no network or API key
```

## Notes

- Summaries are AI-generated from the linked sources and can be wrong. Treat the stock radar as speculation, not advice.
- Feed text is untrusted: the page renders everything as plain text and only opens `http(s)` links.
