"""The daily job: fetch new embargoed releases, triage, review, write a digest.

Used by both the CLI (`agent.py run`) and the web app (scheduler and the
"Run now" button). Only one run can happen at a time per process.
"""

import threading
import traceback
from datetime import date
from typing import Callable

from .browser import EurekaSession, open_session
from .config import Config
from .digest import write_html, write_markdown
from .parse import find_next_page, parse_listing, parse_release
from .store import Store

RUN_LOCK = threading.Lock()


def editorial_profile(cfg: Config, store: Store) -> str:
    """The profile edited in the web app, falling back to editorial_profile.md."""
    saved = store.get_setting("editorial_profile")
    if saved:
        return saved
    path = cfg.default_profile_path
    return path.read_text(encoding="utf-8") if path.exists() else ""


class Pipeline:
    def __init__(self, cfg: Config, store: Store, log: Callable[[str], None] = print):
        self.cfg = cfg
        self.store = store
        self.log = log

    def ensure_login(self, s: EurekaSession) -> bool:
        if s.is_logged_in():
            return True
        self.log("EurekAlert! session expired; logging in with EUREKA_EMAIL/EUREKA_PASSWORD...")
        if s.auto_login():
            self.log("Logged in.")
            return True
        self.log("Login failed. Check the credentials in .env, or log in manually (see README).")
        return False

    def collect_new_releases(self, s: EurekaSession, run_id: int | None) -> list[str]:
        cfg, store = self.cfg, self.store
        seen: dict[str, tuple] = {}
        for start_url in cfg.listing_urls:
            url = start_url
            from_embargo_page = "embargo" in start_url.lower()
            for page_no in range(cfg.max_listing_pages):
                html = s.get(url)
                items = parse_listing(html)
                if not items:
                    cfg.debug_dir.mkdir(parents=True, exist_ok=True)
                    snap = cfg.debug_dir / "empty_listing.html"
                    snap.write_text(html, encoding="utf-8")
                    self.log(f"  no releases found on {url}; page saved to {snap} for debugging")
                new = [i for i in items if not store.has(i.release_id) and i.release_id not in seen]
                self.log(f"  {url} page {page_no + 1}: {len(items)} releases, {len(new)} new")
                for i in new:
                    seen[i.release_id] = (i, from_embargo_page)
                # Listings are newest first: once a whole page is already known, stop paging.
                if items and not new:
                    break
                url = find_next_page(html, url)
                if not url:
                    break

        to_fetch = list(seen.values())[: cfg.max_new_releases]
        fetched: list[str] = []
        for n, (item, from_embargo_page) in enumerate(to_fetch, 1):
            try:
                release = parse_release(s.get(item.url), item.url)
            except Exception as e:
                self.log(f"  [{n}/{len(to_fetch)}] failed {item.url}: {e}")
                continue
            release.release_id = item.release_id
            if not release.embargo_text:
                # Fall back to the listing card, then to the page it came from.
                release.embargo_text = item.embargo_text or ("Embargoed (from embargoed-news list)" if from_embargo_page else "")
            store.add(release, run_id)
            fetched.append(release.release_id)
            tag = "EMBARGOED" if release.is_embargoed else "public"
            self.log(f"  [{n}/{len(to_fetch)}] {tag:9} {release.title[:90]}")
        return fetched

    def run(self, run_id: int | None = None, dry_run: bool = False, include_all: bool = False) -> str:
        cfg, store = self.cfg, self.store
        embargoed_only = cfg.embargoed_only and not include_all

        self.log("Opening EurekAlert!...")
        with open_session(cfg) as s:
            if not self.ensure_login(s):
                raise RuntimeError("Not logged in to EurekAlert!")
            fetched = self.collect_new_releases(s, run_id)
        self.log(f"Fetched {len(fetched)} new releases.")

        candidates = store.untriaged(embargoed_only)
        if embargoed_only and fetched and not candidates:
            self.log("None of the new releases were detected as embargoed; check the listing URL.")
        if dry_run or not candidates:
            return f"{len(fetched)} fetched, nothing to score" if not candidates else f"dry run: {len(candidates)} to triage"

        from .scorer import Scorer  # imported lazily so dry runs work without an API key
        scorer = Scorer(cfg, editorial_profile(cfg, store))

        self.log(f"Triage: {len(candidates)} releases...")
        triage = scorer.triage(candidates)
        for r in candidates:
            item = triage.get(r.release_id)
            store.save_triage(r.release_id, item.model_dump() if item else {"keep": False, "reason": "not returned by triage"})
        keep = [r for r in candidates if triage.get(r.release_id) and triage[r.release_id].keep][: cfg.max_deep_reviews]
        self.log(f"Full review: {len(keep)} releases...")

        reviewed = 0
        for rid, result in scorer.review_many(keep).items():
            if isinstance(result, Exception):
                self.log(f"  review failed for {rid}: {result}")
                continue
            store.save_review(rid, result.model_dump(), result.fit_score)
            reviewed += 1
            self.log(f"  {result.fit_score:>2}/10  {result.headline_idea}")

        results = store.results_for([r.release_id for r in candidates])
        cfg.digest_dir.mkdir(parents=True, exist_ok=True)
        write_markdown(results, cfg.digest_dir, date.today())
        write_html(results, cfg.digest_dir, date.today())
        strong = sum(1 for r in results if r["review"] and r["review"]["verdict"] == "strong pick")
        return f"{len(fetched)} fetched, {len(candidates)} triaged, {reviewed} reviewed, {strong} strong picks"

    def review_one(self, release_id: str) -> None:
        """Full review for a single release (e.g. one a colleague rescued from the triage pile)."""
        from .scorer import Scorer
        scorer = Scorer(self.cfg, editorial_profile(self.cfg, self.store))
        result = scorer.review(self.store.get(release_id))
        self.store.save_review(release_id, result.model_dump(), result.fit_score)


def run_tracked(cfg: Config, store: Store, trigger: str, **kwargs) -> int | None:
    """Run the pipeline with its log recorded in the runs table. Returns None if a run is already going."""
    if not RUN_LOCK.acquire(blocking=False):
        return None
    try:
        if store.active_run() is not None:  # e.g. started by another process
            return None
        run_id = store.start_run(trigger)

        def log(line: str) -> None:
            print(line, flush=True)
            store.append_run_log(run_id, line)

        try:
            summary = Pipeline(cfg, store, log).run(run_id=run_id, **kwargs)
            store.finish_run(run_id, "ok", summary)
        except Exception as e:
            log(traceback.format_exc())
            store.finish_run(run_id, "error", str(e)[:300])
        return run_id
    finally:
        RUN_LOCK.release()
