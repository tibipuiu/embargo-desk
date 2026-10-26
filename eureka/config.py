"""Settings loaded from environment variables / .env (see .env.example)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://www.eurekalert.org"
EMBARGOED_NEWS_URL = f"{BASE_URL}/reporter/embargoed-news"

load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    val = os.getenv(name, "").strip()
    return int(val) if val else default


@dataclass
class Config:
    email: str
    password: str
    listing_urls: list[str]
    max_listing_pages: int
    max_new_releases: int
    embargoed_only: bool
    max_deep_reviews: int
    model: str
    request_delay: float
    headless: bool
    run_times: list[str]
    data_dir: Path
    profile_dir: Path
    db_path: Path
    digest_dir: Path
    debug_dir: Path
    default_profile_path: Path
    secret_key: str
    admin_username: str
    admin_password: str
    secure_cookies: bool


def load_config() -> Config:
    urls = os.getenv("EUREKA_LISTING_URLS", "").strip()
    listing_urls = [u.strip() for u in urls.split(",") if u.strip()] or [EMBARGOED_NEWS_URL]
    data_dir = Path(os.getenv("DATA_DIR", "").strip() or ROOT / "data")
    run_times = [t.strip() for t in os.getenv("RUN_TIMES", "07:00").split(",") if t.strip()]
    return Config(
        email=os.getenv("EUREKA_EMAIL", "").strip(),
        password=os.getenv("EUREKA_PASSWORD", "").strip(),
        listing_urls=listing_urls,
        max_listing_pages=_int("MAX_LISTING_PAGES", 5),
        max_new_releases=_int("MAX_NEW_RELEASES", 150),
        embargoed_only=_bool("EMBARGOED_ONLY", True),
        max_deep_reviews=_int("MAX_DEEP_REVIEWS", 25),
        model=os.getenv("CLAUDE_MODEL", "claude-opus-5-5").strip(),
        request_delay=float(os.getenv("REQUEST_DELAY_SECONDS", "1.5")),
        # EurekAlert! answers headless browsers with 403. Locally a window opens;
        # in Docker, Chromium draws to a virtual display (Xvfb) instead.
        headless=_bool("HEADLESS", False),
        run_times=run_times,
        data_dir=data_dir,
        profile_dir=data_dir / "browser-profile",
        db_path=data_dir / "eureka.db",
        digest_dir=data_dir / "digests",
        debug_dir=data_dir / "debug",
        default_profile_path=ROOT / "editorial_profile.md",
        secret_key=os.getenv("SECRET_KEY", "").strip(),
        admin_username=os.getenv("ADMIN_USERNAME", "").strip(),
        admin_password=os.getenv("ADMIN_PASSWORD", "").strip(),
        secure_cookies=_bool("SECURE_COOKIES", True),
    )
