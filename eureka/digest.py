"""Daily digest: an HTML page to read and a Markdown copy to paste into Slack/notes."""

import html
from datetime import date
from pathlib import Path

VERDICT_ORDER = {"strong pick": 0, "maybe": 1, "skip": 2}


def _sorted(results: list[dict]) -> tuple[list[dict], list[dict]]:
    reviewed = [r for r in results if r["review"]]
    reviewed.sort(key=lambda r: (VERDICT_ORDER.get(r["review"]["verdict"], 3), -(r["score"] or 0)))
    passed = [r for r in results if not r["review"]]
    return reviewed, passed


def write_markdown(results: list[dict], out_dir: Path, day: date) -> Path:
    reviewed, passed = _sorted(results)
    lines = [f"# EurekAlert! embargo picks for {day:%A %d %B %Y}", ""]
    if not reviewed:
        lines.append("_No releases made it past triage today._")
    for r in reviewed:
        rel, rev = r["release"], r["review"]
        lines += [
            f"## [{rev['fit_score']}/10 · {rev['verdict']}] {rev['headline_idea']}",
            f"**Release:** [{rel.title}]({rel.url})  ",
            f"**From:** {rel.institution} · **Journal:** {rel.journal or 'n/a'} · **DOI:** {rel.doi or 'n/a'}  ",
            f"**Embargo:** {rel.embargo_text or 'not detected'} · **Topic:** {rev['topic']} · "
            f"**Study type:** {rev['study_type']} · **Visuals:** {rev['visual_potential']}",
            "",
            f"**Hook:** {rev['hook']}",
            "",
            f"**Key finding:** {rev['key_finding']}",
            "",
            f"**Why it fits:** {rev['why_it_fits']}",
            "",
        ]
        if rev["caveats"]:
            lines.append("**Caveats:**")
            lines += [f"- {c}" for c in rev["caveats"]]
            lines.append("")
    if passed:
        lines += ["---", f"## Passed over at triage ({len(passed)})", ""]
        lines += [f"- [{r['release'].title}]({r['release'].url}): {r['triage'].get('reason', '')}" for r in passed]
    path = out_dir / f"{day:%Y-%m-%d}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_html(results: list[dict], out_dir: Path, day: date) -> Path:
    e = html.escape
    reviewed, passed = _sorted(results)
    cards = []
    for r in reviewed:
        rel, rev = r["release"], r["review"]
        caveats = "".join(f"<li>{e(c)}</li>" for c in rev["caveats"])
        cards.append(f"""
<article class="card {e(rev['verdict'].replace(' ', '-'))}">
  <div class="score">{rev['fit_score']}<small>/10</small></div>
  <div class="content">
    <p class="kicker">{e(rev['topic'])} · {e(rev['verdict'])} · visuals: {e(rev['visual_potential'])}</p>
    <h2>{e(rev['headline_idea'])}</h2>
    <p class="hook">{e(rev['hook'])}</p>
    <p><strong>Key finding:</strong> {e(rev['key_finding'])}</p>
    <p><strong>Why it fits:</strong> {e(rev['why_it_fits'])}</p>
    {f'<p><strong>Caveats:</strong></p><ul>{caveats}</ul>' if caveats else ''}
    <dl>
      <dt>Release</dt><dd><a href="{e(rel.url)}">{e(rel.title)}</a></dd>
      <dt>From</dt><dd>{e(rel.institution)}</dd>
      <dt>Journal</dt><dd>{e(rel.journal or 'n/a')}{' · DOI ' + e(rel.doi) if rel.doi else ''}</dd>
      <dt>Embargo</dt><dd>{e(rel.embargo_text or 'not detected')}</dd>
      <dt>Study type</dt><dd>{e(rev['study_type'])}</dd>
    </dl>
  </div>
</article>""")
    passed_items = "".join(
        f"<li><a href=\"{e(r['release'].url)}\">{e(r['release'].title)}</a> <span>{e(r['triage'].get('reason', ''))}</span></li>"
        for r in passed
    )
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Embargo picks {day:%Y-%m-%d}</title>
<style>
:root {{ --bg:#f6f5f1; --card:#fff; --ink:#1c1c1c; --muted:#666; --line:#e2dfd6; --strong:#1f7a4d; --maybe:#b7791f; --skip:#999; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141414; --card:#1e1e1e; --ink:#eee; --muted:#aaa; --line:#333; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.55 Georgia, serif; }}
main {{ max-width:860px; margin:0 auto; padding:32px 16px 64px; }}
h1 {{ font-size:28px; margin:0 0 4px; }} .sub {{ color:var(--muted); margin:0 0 28px; font-family:system-ui,sans-serif; font-size:14px; }}
.card {{ display:flex; gap:18px; background:var(--card); border:1px solid var(--line); border-left:5px solid var(--skip); border-radius:8px; padding:18px 20px; margin-bottom:16px; }}
.card.strong-pick {{ border-left-color:var(--strong); }} .card.maybe {{ border-left-color:var(--maybe); }}
.score {{ font:700 30px/1 system-ui,sans-serif; min-width:56px; }} .score small {{ font-size:13px; color:var(--muted); }}
.content {{ flex:1; min-width:0; }} .kicker {{ margin:0; text-transform:uppercase; letter-spacing:.06em; font:600 11px system-ui,sans-serif; color:var(--muted); }}
h2 {{ margin:6px 0 8px; font-size:21px; line-height:1.3; }} .hook {{ font-style:italic; }}
dl {{ display:grid; grid-template-columns:max-content 1fr; gap:2px 12px; font:13px/1.5 system-ui,sans-serif; color:var(--muted); margin:12px 0 0; }}
dt {{ font-weight:600; }} dd {{ margin:0; overflow-wrap:anywhere; }} a {{ color:inherit; }}
details {{ margin-top:32px; font-family:system-ui,sans-serif; font-size:14px; }} details li span {{ color:var(--muted); }}
@media (max-width:560px) {{ .card {{ flex-direction:column; gap:6px; }} }}
</style></head><body><main>
<h1>Embargo picks</h1>
<p class="sub">{day:%A %d %B %Y} · {len(reviewed)} reviewed · {len(passed)} passed over at triage</p>
{''.join(cards) or '<p>No releases made it past triage today.</p>'}
{f'<details><summary>Passed over at triage ({len(passed)})</summary><ul>{passed_items}</ul></details>' if passed else ''}
</main></body></html>"""
    path = out_dir / f"{day:%Y-%m-%d}.html"
    path.write_text(page, encoding="utf-8")
    return path
