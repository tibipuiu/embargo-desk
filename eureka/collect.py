"""Browser side of the agent: read the embargoed listing and fetch release pages.

Runs on a colleague's computer (see collect.py), never on the server: the
server is too small to run a browser.
"""

from typing import Callable, Iterable

from .browser import EurekaSession
from .config import Config
from .parse import ListingItem, Release, find_next_page, parse_listing, parse_release

Log = Callable[[str], None]
KnownFilter = Callable[[list[str]], set[str]]


def gather_listing(s: EurekaSession, cfg: Config, known: KnownFilter, log: Log) -> list[tuple[ListingItem, bool]]:
    """New listing items, newest first, as (item, came_from_embargo_page) pairs.

    `known` takes release ids and returns the ones already in Embargo Desk,
    so pages already fetched (by anyone) aren't opened again.
    """
    seen: dict[str, tuple[ListingItem, bool]] = {}
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
                log(f"  No releases found on {url}. Page saved to {snap} for debugging.")
            candidates = [i for i in items if i.release_id not in seen]
            already = known([i.release_id for i in candidates]) if candidates else set()
            new = [i for i in candidates if i.release_id not in already]
            log(f"  Listing page {page_no + 1}: {len(items)} releases, {len(new)} new")
            for i in new:
                seen[i.release_id] = (i, from_embargo_page)
            # Listings are newest first: once a whole page is already known, stop paging.
            if items and not new:
                break
            url = find_next_page(html, url)
            if not url:
                break
    return list(seen.values())[: cfg.max_new_releases]


def fetch_releases(s: EurekaSession, items: Iterable[tuple[ListingItem, bool]], log: Log) -> list[Release]:
    items = list(items)
    releases: list[Release] = []
    for n, (item, from_embargo_page) in enumerate(items, 1):
        try:
            release = parse_release(s.get(item.url), item.url)
        except Exception as e:
            log(f"  [{n}/{len(items)}] failed {item.url}: {e}")
            continue
        release.release_id = item.release_id
        if not release.embargo_text:
            # Fall back to the listing card, then to the page it came from.
            release.embargo_text = item.embargo_text or ("Embargoed (from embargoed-news list)" if from_embargo_page else "")
        releases.append(release)
        tag = "EMBARGOED" if release.is_embargoed else "public"
        log(f"  [{n}/{len(items)}] {tag:9} {release.title[:80]}")
    return releases
