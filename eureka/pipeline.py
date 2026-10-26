"""Server side of the agent: score uploaded releases with Claude and write a digest.

Releases arrive from a colleague's computer (collect.py -> /api/upload). The
web app then starts `agent.py score --run-id N` in a separate process, which
calls score_run() below.
"""

import traceback
from datetime import date
from typing import Callable

from .config import Config
from .digest import write_html, write_markdown
from .store import Store


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

    def score(self) -> str:
        """Triage and review every release that hasn't been triaged yet."""
        cfg, store = self.cfg, self.store
        candidates = store.untriaged(cfg.embargoed_only)
        if not candidates:
            return "nothing to score"

        from .scorer import Scorer  # imported lazily so the web app starts without the Anthropic SDK loaded
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
        return f"{len(candidates)} triaged, {reviewed} reviewed, {strong} strong picks"

    def review_one(self, release_id: str) -> None:
        """Full review for a single release (e.g. one a colleague rescued from the triage pile)."""
        from .scorer import Scorer
        scorer = Scorer(self.cfg, editorial_profile(self.cfg, self.store))
        result = scorer.review(self.store.get(release_id))
        self.store.save_review(release_id, result.model_dump(), result.fit_score)


def score_run(cfg: Config, store: Store, run_id: int) -> None:
    """Score pending releases, logging into run `run_id` and finishing it."""
    def log(line: str) -> None:
        print(line, flush=True)
        store.append_run_log(run_id, line)

    run = store.run(run_id)
    prefix = f"{run['summary']} · " if run and run["summary"] else ""
    try:
        summary = Pipeline(cfg, store, log).score()
        store.finish_run(run_id, "ok", prefix + summary)
    except Exception as e:
        log(traceback.format_exc())
        store.finish_run(run_id, "error", prefix + str(e)[:300])
