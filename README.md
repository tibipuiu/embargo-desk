# Embargo Desk: EurekAlert! story scout for ZME Science

A shared web app for the ZME Science newsroom. Every day an agent logs in to EurekAlert! with a
reporter account, reads the new releases on
[the embargoed-news page](https://www.eurekalert.org/reporter/embargoed-news), and has Claude pick
the ones that would make good popular-science stories. The team sees the picks on one board,
claims stories, tracks them from *claimed* to *published*, and leaves notes for each other.

## What the team sees

- **Picks.** Cards sorted by fit score, each with a working headline, the reader hook, the
  source release, caveats (mouse study, small sample, hype...) and a countdown to the embargo
  lift. One click, "I'll take it", claims a story. You can filter by verdict, status and date,
  or sort by soonest embargo.
- **Release page.** The full review: key finding, why it fits, study type, caveats. Also the
  press release itself (full text, journal, DOI, media contact), a status and writer picker, and a
  notes thread.
- **Passed over.** Releases the agent dropped after reading only the title and opening, with its
  reason. If it got one wrong, open it and click **Request full review**.
- **Runs.** History and logs of every run, plus a **Run now** button.
- **Settings** (admins only). Edit the editorial profile that steers the picks, and add or
  remove colleagues and reset their passwords.

## How the agent works

1. **Fetch.** Chromium, driven by Playwright, logs in with the reporter account, reads the
   embargoed listing, and opens each new release. Releases are stored in SQLite, so none is
   fetched or scored twice.
2. **Triage.** Claude reads titles and opening paragraphs in batches of 40 and keeps roughly the
   top quarter (low effort, cheap).
3. **Review.** Claude reads the full text of up to 25 survivors and returns a structured review.
4. **Board.** Results appear in the web app. A dated HTML/Markdown digest is also written to
   `data/digests/`.

## Deploy with Coolify (embargodesk.zmescience.com)

Coolify builds the app from a Git repository and handles the domain and HTTPS through its own
proxy. The repo's `docker-compose.yml` is written for Coolify's **Docker Compose** build pack.

1. **DNS:** add an A record for `embargodesk.zmescience.com` pointing at the Coolify server
   (skip this if you already have a wildcard `*.zmescience.com` record pointing there).
2. **Git:** push this folder to a **private** GitHub repo. `.gitignore` keeps out `.env`,
   `.venv`, `data/` and the browser session.
3. **Coolify, new resource:** *Private Repository (with GitHub App)*, or *Deploy Key* for
   another Git host. Pick the repo and branch, then set **Build Pack: Docker Compose** with the
   compose file `/docker-compose.yml`.
4. **Domain:** in the resource's configuration, set the domain of the `app` service to
   `https://embargodesk.zmescience.com:8000`. The `:8000` tells Coolify which container port to
   route to; people just visit `https://embargodesk.zmescience.com`.
5. **Environment Variables** tab (they come from `docker-compose.yml`; required ones are flagged):
   - `SECRET_KEY`: a long random string, e.g. from
     `python -c "import secrets; print(secrets.token_urlsafe(48))"`
   - `ADMIN_USERNAME`, `ADMIN_PASSWORD`: your first admin account
   - `ANTHROPIC_API_KEY`
   - `EUREKA_EMAIL`, `EUREKA_PASSWORD`: the reporter login the server uses
   - optional: `TZ` (default `Europe/Bucharest`), `RUN_TIMES` (default `07:00`), `CLAUDE_MODEL`,
     and the limits listed under *Settings* below
6. **Deploy.** The first build takes a few minutes (the Playwright base image is large).

Then open https://embargodesk.zmescience.com, log in as the admin, add your colleagues under
**Settings**, and press **Run now** on the **Runs** page for a first run. Once you've logged in
successfully, you can delete `ADMIN_PASSWORD` in Coolify; the account stays.

**Data:** the database, EurekAlert! session and digests live in the `embargo-data` volume,
mounted at `/data`. Coolify keeps it across redeploys and shows it under *Persistent Storage*.
Add it to Coolify's backups.

**Updates:** push to the branch and redeploy (or turn on auto-deploy on push).

**Command-line tools:** open the container's **Terminal** in Coolify and run, for example,
`python agent.py discover` or `python agent.py create-user jane --name "Jane Doe"`.

**Coolify v3 (3.x):** v3 has no Docker Compose build pack, so use the Dockerfile instead.
*Create New Resource → Application*, pick your GitHub Git Source, the `embargo-desk` repo and
branch `main`, then build pack **Docker**. In the application's settings:
- **Domain** `https://embargodesk.zmescience.com`, **Port** `8000`
- **Base Directory** `/`, **Dockerfile Location** `/Dockerfile`
- **Secrets:** add the variables from step 5, plus `TZ` and `RUN_TIMES` if you want to change
  the defaults. Leave *Build Secret* off for all of them.
- **Storage:** add a persistent volume at `/data`. Without it, the database and team notes are
  lost on every redeploy.

**Without Coolify:** on any Docker host, `docker compose up -d --build` runs the same container
on port 8000. Put a reverse proxy with HTTPS in front of it, and pass the variables in an
`.env` file next to the compose file.

## First run checklist

The logged-in embargoed-news page can only be seen with a reporter account, so the parser for it
is built to tolerate an unknown layout. After the first run, check the **Runs** log:

- `N releases, N new` with N > 0 means the listing parsed.
- `EMBARGOED` tags on the fetched releases mean embargo detection works. Releases found on the
  embargoed-news page count as embargoed even if no lift time is found.
- If it says *no releases found*, the page was saved to `data/debug/empty_listing.html`. Send that
  file to whoever maintains this (or to Claude) to adjust `eureka/parse.py`. The command
  `docker compose exec app python agent.py discover` saves more snapshots.

## Things to know

- **Sharing embargoed material.** EurekAlert! reporter accounts belong to individual journalists,
  and its terms forbid sharing account passwords. Everyone on this board sees embargoed releases
  fetched with one account. Ideally each colleague has their own EurekAlert! reporter
  registration, and you should check with EurekAlert! that a shared team tool like this is fine.
  The app is login-only and marked `noindex`, but the material is still embargoed: treat it that
  way.
- **Automated access.** EurekAlert! returns 403 to headless browsers. In Docker, the agent runs a
  normal Chromium on a virtual display (Xvfb), logged in as your account, loading one page every
  1.5 s and at most ~150 releases per run. That is still automated access. If EurekAlert!
  objects, the cleaner route is their embargoed email alerts: subscribe the reporter account and
  have the agent read that inbox instead.
- **EurekAlert! login on the server.** There is no screen to type into, so the server logs in by
  itself with `EUREKA_EMAIL` / `EUREKA_PASSWORD`. If AAAS adds a CAPTCHA or two-factor step, that
  automatic login will fail and the run log will say so; a remote-browser login helper would be
  the next thing to add.
- **Data sent to Claude.** Release text goes to the Anthropic API for scoring. Anthropic doesn't
  train on API data by default.
- **Cost.** About $1–2 a day with Claude Opus 5.5 at ~150 releases. Lower `MAX_DEEP_REVIEWS` or
  set `CLAUDE_MODEL=claude-sonnet-5-5` to roughly halve that.

## Run locally (development)

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
copy .env.example .env   # set SECRET_KEY, ADMIN_*, ANTHROPIC_API_KEY
.venv\Scripts\python agent.py login          # log in to EurekAlert! yourself in the window that opens
.venv\Scripts\python -m uvicorn web.app:app --reload
```

Then open http://localhost:8000. Tests: `.venv\Scripts\python -m pytest`.

## Settings (`.env`)

| Setting | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | | Signs login cookies (required) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | | First admin, created when no accounts exist |
| `SECURE_COOKIES` | `true` | Set `false` only for local http |
| `TZ` / `RUN_TIMES` | `Europe/Bucharest` / `07:00` | Server time zone and daily run times (comma-separated) |
| `ANTHROPIC_API_KEY` | | Claude API key |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Model for triage and review |
| `EUREKA_EMAIL` / `EUREKA_PASSWORD` | | Reporter login used by the server |
| `EUREKA_LISTING_URLS` | reporter/embargoed-news | Listing page(s) to scan |
| `EMBARGOED_ONLY` | `true` | Ignore releases not detected as embargoed |
| `MAX_LISTING_PAGES` | 5 | Pages to follow per listing (stops early at known releases) |
| `MAX_NEW_RELEASES` | 150 | Release pages opened per run |
| `MAX_DEEP_REVIEWS` | 25 | Full Claude reviews per run |
| `REQUEST_DELAY_SECONDS` | 1.5 | Pause between page loads |

## Project layout

```
web/app.py            FastAPI app: login, board, release pages, runs, settings
web/templates/        Jinja2 pages        web/static/style.css
eureka/pipeline.py    The daily job (fetch, triage, review, digest)
eureka/scheduler.py   Runs the job at RUN_TIMES
eureka/browser.py     Logged-in Playwright session
eureka/parse.py       Listing and release HTML parsing
eureka/scorer.py      Claude triage + review (structured outputs)
eureka/store.py       SQLite: releases, users, notes, runs, settings
eureka/digest.py      HTML + Markdown digest files
agent.py              CLI: login, discover, run, create-user
editorial_profile.md  Default editorial profile (editable in Settings)
Dockerfile, docker-compose.yml   Container build + Coolify deployment
```

## Roadmap

- **v2: Questions for study authors.** For each pick, draft interview questions covering both
  the findings (effect sizes, limits, what's new) and the story (how the idea started, surprises,
  what it means for readers, what's next), written for a general audience. They would show on the
  release page next to the notes.
- **v3: Outside experts.** Find independent researchers in the field (OpenAlex / Semantic
  Scholar plus web search), check for conflicts such as co-authorship, and draft questions asking
  them to put the findings in context.
- Smaller ideas: a morning email or Slack post with the top picks, thumbs up/down feedback that
  refines the editorial profile, and a check against stories ZME has already published.
