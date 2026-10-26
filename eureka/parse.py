"""HTML parsing for EurekAlert! listing pages and individual news releases.

Selectors were taken from the public site (October 2026). The logged-in
reporter view may differ slightly; run `python agent.py discover` to save
snapshots to debug/ if parsing comes back empty.
"""

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .config import BASE_URL

# Public releases live at /news-releases/<id>; embargoed ones may sit under
# /reporter/... or /embargoed-news/... in the logged-in view.
RELEASE_RE = re.compile(r"/(?:news-releases|embargoed-news|reporter/[\w-]+)/(\d{4,})(?:[/?#]|$)")
EMBARGO_RE = re.compile(r"embargo(?:ed)?\b[^\n]{0,120}", re.I)
LOGGED_IN_RE = re.compile(r"log\s*out|logout|sign\s*out|my\s+account|my\s+profile", re.I)
EMBARGO_DATE_RE = re.compile(
    r"(\d{1,2})[-\s]([A-Za-z]{3})[A-Za-z]*[-\s,]+(\d{4})(?:\D{0,12}?(\d{1,2}):(\d{2})\s*(AM|PM)?)?", re.I
)


def parse_embargo_datetime(text: str) -> datetime | None:
    """Best-effort '28-Oct-2026 11:00 ET' -> naive datetime in the listed (US Eastern) time."""
    m = EMBARGO_DATE_RE.search(text or "")
    if not m:
        return None
    day, mon, year, hour, minute, ampm = m.groups()
    try:
        dt = datetime.strptime(f"{day} {mon[:3].title()} {year}", "%d %b %Y")
    except ValueError:
        return None
    if hour:
        h = int(hour) % 12 + (12 if ampm and ampm.upper() == "PM" else 0) if ampm else int(hour)
        dt = dt.replace(hour=h, minute=int(minute))
    return dt


def _text(el: Tag | None) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _dl_pairs(dl: Tag | None) -> dict[str, str]:
    """Turn <dl><dt>Journal</dt><dd>Nature</dd>... into {'journal': 'Nature'}."""
    pairs: dict[str, str] = {}
    if not dl:
        return pairs
    for dt in dl.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            pairs[_text(dt).lower()] = _text(dd)
    return pairs


def _embargo_text(el: Tag | None) -> str:
    """Return the first 'Embargoed until ...' style snippet inside el, if any."""
    if not el:
        return ""
    m = EMBARGO_RE.search(el.get_text(" ", strip=True))
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else ""


@dataclass
class ListingItem:
    release_id: str
    url: str
    title: str
    institution: str = ""
    date_text: str = ""
    summary: str = ""
    journal: str = ""
    embargo_text: str = ""


@dataclass
class Release:
    release_id: str
    url: str
    title: str
    subtitle: str = ""
    institution: str = ""
    date_text: str = ""
    release_type: str = ""
    journal: str = ""
    doi: str = ""
    funder: str = ""
    embargo_text: str = ""
    body: str = ""
    contacts: str = ""

    @property
    def is_embargoed(self) -> bool:
        return bool(self.embargo_text)

    @property
    def embargo_until(self) -> datetime | None:
        return parse_embargo_datetime(self.embargo_text)

    def to_dict(self) -> dict:
        return asdict(self)


def parse_listing(html: str, base_url: str = BASE_URL) -> list[ListingItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: dict[str, ListingItem] = {}
    for art in soup.select("article.post"):
        link = art.find("a", href=RELEASE_RE)
        if not link:
            continue
        rid = RELEASE_RE.search(link["href"]).group(1)
        meta = _dl_pairs(art.select_one("dl.meta"))
        items[rid] = ListingItem(
            release_id=rid,
            url=urljoin(base_url, link["href"]),
            title=_text(art.select_one(".post_title")) or _text(link),
            institution=_text(art.select_one(".author")),
            date_text=_text(art.select_one(".reltime")),
            summary=_text(art.select_one(".intro")),
            journal=meta.get("journal", ""),
            embargo_text=_embargo_text(art),
        )
    if items:
        return list(items.values())

    # Unknown layout (e.g. the reporter-only embargo page): fall back to every
    # link that points at a release, using the surrounding block for context.
    for link in soup.find_all("a", href=RELEASE_RE):
        rid = RELEASE_RE.search(link["href"]).group(1)
        title = _text(link)
        if rid in items or len(title) < 15:
            continue
        block = link.find_parent(["li", "tr", "article", "div"]) or link
        items[rid] = ListingItem(
            release_id=rid,
            url=urljoin(base_url, link["href"]),
            title=title,
            embargo_text=_embargo_text(block),
        )
    return list(items.values())


def find_next_page(html: str, current_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("a", rel="next")
    if not link:
        link = soup.find("a", string=re.compile(r"^\s*(next|›|»|>)\s*$", re.I))
    if link and link.get("href"):
        return urljoin(current_url, link["href"])
    return None


def parse_release(html: str, url: str) -> Release:
    soup = BeautifulSoup(html, "html.parser")
    rid_match = RELEASE_RE.search(url)
    article = soup.select_one(".article") or soup
    header = article.find("header") or article
    meta = _dl_pairs(soup.select_one("dl.meta"))

    release_type = ""
    guideline_link = header.find("a", href=re.compile(r"releaseguidelines"))
    if guideline_link:
        release_type = _text(guideline_link)

    # The embargo banner can live in the header, in a page-level alert, or in
    # the date line, so check the most specific places first.
    embargo = (
        _embargo_text(header)
        or _embargo_text(soup.select_one(".alert, .embargo, .embargoed"))
        or _embargo_text(soup.select_one(".release_date"))
    )

    entry = soup.select_one(".entry")
    body = ""
    if entry:
        for fig in entry.find_all("figure"):
            fig.decompose()
        body = entry.get_text("\n", strip=True)

    return Release(
        release_id=rid_match.group(1) if rid_match else url,
        url=url,
        title=_text(soup.select_one("h1.page_title")) or _text(soup.find("h1")),
        subtitle=_text(soup.select_one("p.subtitle")),
        institution=_text(soup.select_one(".meta_institute")),
        date_text=re.sub(r"^News Release\s*", "", _text(soup.select_one(".release_date"))),
        release_type=release_type,
        journal=meta.get("journal", ""),
        doi=meta.get("doi", ""),
        funder=meta.get("funder", ""),
        embargo_text=embargo,
        body=body,
        contacts=_text(soup.select_one(".contact-info")),
    )


def looks_logged_in(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a"):
        if LOGGED_IN_RE.search(a.get_text(" ", strip=True)) or LOGGED_IN_RE.search(a.get("href", "")):
            return True
    return False


def embargo_links(html: str, base_url: str = BASE_URL) -> list[tuple[str, str]]:
    """Links whose text or URL mentions embargoes; used by `discover`."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        if re.search(r"embargo", label + " " + a["href"], re.I):
            found.append((label, urljoin(base_url, a["href"])))
    return found
