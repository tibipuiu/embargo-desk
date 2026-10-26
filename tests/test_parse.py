from pathlib import Path

from eureka.parse import find_next_page, looks_logged_in, parse_listing, parse_release

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_listing_cards():
    items = parse_listing(read("browse.html"))
    assert [i.release_id for i in items] == ["1148969", "1148415", "1150001"]
    first = items[0]
    assert first.url == "https://www.eurekalert.org/news-releases/1148969"
    assert first.title.startswith("Researchers create the first multi-omic atlas")
    assert first.institution == "Universidad Miguel Hernandez de Elche"
    assert first.journal == "Nature Neuroscience"
    assert first.embargo_text == ""
    assert items[2].embargo_text.startswith("Embargoed until 28-Oct-2026")


def test_next_page():
    url = "https://www.eurekalert.org/news-releases/browse/all"
    assert find_next_page(read("browse.html"), url) == "https://www.eurekalert.org/news-releases/browse/all?page=2"


def test_parse_release():
    rel = parse_release(read("release.html"), "https://www.eurekalert.org/news-releases/1148969")
    assert rel.release_id == "1148969"
    assert rel.title.startswith("Researchers create the first multi-omic atlas")
    assert rel.release_type == "Peer-Reviewed Publication"
    assert rel.journal == "Nature Neuroscience"
    assert rel.doi == "10.1038/s41593-026-02485-9"
    assert rel.is_embargoed and "28-Oct-2026" in rel.embargo_text
    assert "SP9" in rel.body
    assert "Fluorescence image" not in rel.body  # figure captions are dropped
    assert "press@umh.es" in rel.contacts


def test_listing_fallback_for_unknown_layout():
    html = """<table>
      <tr><td><a href="/reporter/embargoed-news/1151234">Octopuses dream in color, sleep study suggests</a></td>
          <td>Embargoed until 30-Oct-2026 14:00 ET</td></tr>
      <tr><td><a href="/news-releases/1151235">Coral reefs recover faster than expected</a></td><td></td></tr>
      <tr><td><a href="/news-releases/browse">Browse</a></td></tr>
    </table>"""
    items = parse_listing(html)
    assert [i.release_id for i in items] == ["1151234", "1151235"]
    assert items[0].url == "https://www.eurekalert.org/reporter/embargoed-news/1151234"
    assert "30-Oct-2026" in items[0].embargo_text


def test_embargo_datetime():
    from datetime import datetime
    from eureka.parse import parse_embargo_datetime
    assert parse_embargo_datetime("Embargoed until 28-Oct-2026 11:00 ET") == datetime(2026, 10, 28, 11, 0)
    assert parse_embargo_datetime("Embargoed until 3 November 2026 2:00 PM ET") == datetime(2026, 11, 3, 14, 0)
    assert parse_embargo_datetime("Embargoed") is None


def test_logged_in_detection():
    assert looks_logged_in(read("release.html"))
    assert not looks_logged_in(read("browse.html"))
