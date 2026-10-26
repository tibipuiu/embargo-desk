# Embargo Desk: EurekAlert! story scout for ZME Science

A shared web app for the ZME Science newsroom, at https://embargodesk.zmescience.com.

Someone on the team runs the **fetcher** on their computer. It opens
[EurekAlert!'s embargoed news](https://www.eurekalert.org/reporter/embargoed-news) in a browser
window, logged in with their own reporter account, collects new embargoed releases, and uploads
them. The server then has Claude pick the ones that would make good popular-science stories,
and the team works from one board: claim a story, track it from *claimed* to *published*, and
leave notes for each other.

## How it fits together

```
 Colleague's computer                      Server (Coolify)
 ───────────────────                       ────────────────
 fetcher (collect.py)                      web app (web/app.py)
   opens EurekAlert! in Chromium   ──►       /api/upload stores new releases
   asks which releases are new     ◄──►      /api/known
   uploads the new ones                      starts `agent.py score` in a separate process
                                               Claude triage → full review of the best
                                             board, release pages, notes, runs
```

**Why fetching happens on people's computers.** EurekAlert! refuses headless browsers, so the
fetcher needs a real browser window, and Chromium needs more memory than the server has spare
(~2 GB shared with Plausible, ClickHouse and Coolify). Running it on a desktop is also what
EurekAlert! expects: each person uses their own reporter account in their own browser. The
server only runs the website and the Claude calls, which are light.

## What the team sees

- **Picks.** Cards sorted by fit score, each with a working headline, the reader hook, the
  source release, caveats (mouse study, small sample, hype...) and a countdown to the embargo
  lift. One click, "I'll take it", claims a story.
- **Release page.** The full review, the press release itself (full text, journal, DOI, media
  contact), a status and writer picker, and a notes thread.
- **Passed over.** Releases dropped at triage, with the reason. **Request full review** rescues
  one.
- **Fetch.** Download your personal fetcher and the setup steps.
- **Runs.** Every upload and its scoring log. Admins can re-score releases left waiting after a
  failure.
- **Settings** (admins only). The editorial profile that steers the picks, and team accounts.

## The fetcher (for colleagues)

1. In Embargo Desk, open **Fetch** and click **Download the fetcher**. The zip contains your
   personal upload key, so don't share it. Downloading again replaces the old key.
2. Unzip it somewhere permanent. Run **1 - Set up (Windows)** (on a Mac, right-click
   **1 - Set up (Mac)** → Open). If Python isn't installed, setup opens python.org for you.
3. To fetch, double-click **2 - Fetch embargoes**. The first time, log in to EurekAlert! in the
   window that opens with your own reporter account; it's remembered after that.

Releases already uploaded by anyone are skipped, so one person fetching each morning is enough.
The only prerequisite is Python 3.10+; setup installs the rest, including the fetcher's own
Chromium (about 150 MB), without touching the normal browser.

## Deploy with Coolify

### Coolify v3 (what zmescience uses)
*Create New Resource → Application*, pick the GitHub source, repo `embargo-desk`, branch `main`,
build pack **Docker**. Then, in the application's settings:

- **Domain** `https://embargodesk.zmescience.com`, **Port** `8000`
- **Base Directory** `/`, **Dockerfile Location** `/Dockerfile`
- **Secrets** (leave *Build Secret* off):
  - `SECRET_KEY`: a long random string, e.g. from
    `python -c "import secrets; print(secrets.token_urlsafe(48))"`
  - `ADMIN_USERNAME`, `ADMIN_PASSWORD`: the first admin account
  - `ANTHROPIC_API_KEY`
  - optional: `TZ`, `CLAUDE_MODEL`, `MAX_DEEP_REVIEWS`, `EMBARGOED_ONLY`
- **Storage:** a persistent volume at **`/data`**. Without it the database (accounts, claims,
  notes) is wiped on every deploy.

**DNS:** an A record for `embargodesk` pointing at the server, set to **DNS only** (grey
cloud) in Cloudflare, so Coolify can issue the HTTPS certificate itself.

### Coolify v4 or plain Docker
Use the **Docker Compose** build pack with `/docker-compose.yml`, and set the `app` service's
domain to `https://embargodesk.zmescience.com:8000`. Without Coolify, `docker compose up -d
--build` runs it on port 8000 behind your own HTTPS proxy.

**Updates:** push to `main` and redeploy. **Backups:** back up the `/data` volume.

**Add accounts from the command line** (Coolify terminal, or `docker exec` into the container):
`python agent.py create-user jane --name "Jane Doe"`.

## First fetch checklist

The logged-in embargoed-news page can only be seen with a reporter account, so the parser is
built to tolerate an unknown layout. After the first fetch, open its run on the **Runs** page:

- `Listing page 1: N releases, N new` with N > 0 means the listing parsed.
- `EMBARGOED` tags on the fetched releases mean embargo detection works. Releases found on the
  embargoed-news page count as embargoed even if no lift time is found.
- If it says *No releases found*, the page was saved in the fetcher folder under
  `data/debug/`. `2 - Fetch embargoes` with `--discover` (or `python collect.py --discover`)
  saves more snapshots. Send them to whoever maintains this (or to Claude) to adjust
  `eureka/parse.py`.

## Things to know

- **Embargoed material.** Everyone on the board sees releases fetched with someone's reporter
  account. Ideally each colleague who fetches has their own EurekAlert! registration, and it's
  worth confirming with EurekAlert! that a shared team board is fine. The app is login-only and
  marked `noindex`, but the material is still embargoed: treat it that way.
- **Automated access.** The fetcher is a normal Chromium window driven by a script: one page
  every 1.5 s, at most ~150 releases per fetch, with images, video and fonts skipped. If
  EurekAlert! objects, the alternative is their embargoed email alerts (see Roadmap).
- **Data sent to Claude.** Release text goes to the Anthropic API for scoring. Anthropic doesn't
  train on API data by default.
- **Cost.** About $1–2 per daily fetch with Claude Opus 5.5 at ~150 releases. Lower
  `MAX_DEEP_REVIEWS` or set `CLAUDE_MODEL=claude-sonnet-5-5` to roughly halve that.

## Run locally (development)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
copy .env.example .env            # set SECRET_KEY, ADMIN_*, ANTHROPIC_API_KEY
.venv\Scripts\python -m uvicorn web.app:app --reload
```

Then open http://localhost:8000, download the fetcher from **Fetch** (it points at localhost),
and run it. Tests: `.venv\Scripts\python -m pytest`.

## Settings (server environment)

| Setting | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | | Signs login cookies (required) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | | First admin, created when no accounts exist |
| `SECURE_COOKIES` | `true` | Set `false` only for local http |
| `TZ` | `Europe/Bucharest` | Time zone for dates on the site |
| `ANTHROPIC_API_KEY` | | Claude API key (required) |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model for triage and review |
| `EMBARGOED_ONLY` | `true` | Ignore releases not detected as embargoed |
| `MAX_DEEP_REVIEWS` | 25 | Full Claude reviews per run |

The fetcher's own limits (`MAX_LISTING_PAGES`, `MAX_NEW_RELEASES`, `REQUEST_DELAY_SECONDS`,
`EUREKA_LISTING_URLS`) can be set in a `.env` file next to `collect.py`; the defaults suit daily
use.

## Project layout

```
web/app.py              Website + upload API + fetcher download
web/templates/, static/ Pages and styles
eureka/pipeline.py      Server: Claude triage + review of uploaded releases, digest
eureka/runner.py        Server: runs scoring in a separate low-priority process, one at a time
eureka/scorer.py        Claude prompts and structured outputs
eureka/store.py         SQLite: releases, users, upload keys, notes, runs, settings
eureka/digest.py        Dated HTML + Markdown digests in /data/digests
agent.py                Server CLI: create-user, score
collect.py              Fetcher entry point (runs on colleagues' computers)
eureka/collect.py       Fetcher: read the listing, fetch release pages
eureka/browser.py       Fetcher: logged-in Chromium session
eureka/parse.py         EurekAlert! HTML parsing
collector/              Fetcher setup/launch scripts and readme (packed into the download)
editorial_profile.md    Default editorial profile (editable in Settings)
Dockerfile, docker-compose.yml
```

## Roadmap

- **v2: Questions for study authors.** For each pick, draft interview questions covering the
  findings (effect sizes, limits, what's new) and the story (how the idea started, surprises,
  what it means for readers, what's next), written for a general audience.
- **v3: Outside experts.** Find independent researchers in the field (OpenAlex / Semantic
  Scholar plus web search), check for conflicts such as co-authorship, and draft questions asking
  them to put the findings in context.
- **Email alerts instead of a browser,** if EurekAlert!'s embargoed alert emails carry enough of
  each release.
- Smaller ideas: a morning email or Slack post with the top picks, thumbs up/down feedback that
  refines the editorial profile, and a check against stories ZME has already published.
