#!/usr/bin/env python3
"""Generate PCB-themed profile cards (SVG) from GitHub data.

Usage: GITHUB_TOKEN=... python3 scripts/gen_cards.py
Reads scripts/cards.json, writes assets/<card>-{dark,light}.svg

Every card follows one template: PCB board + silkscreen refdes + one IC whose
body carries the content + copper traces from its pins to vias.
SVG widths equal their rendered width in the README (830 / 415 / 277 px),
so font sizes are real pixels.
"""
import base64
import json
import math
import os
import textwrap
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "scripts" / "cards.json").read_text(encoding="utf-8"))
OUT = ROOT / "assets"
SANS = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
MONO = "'SFMono-Regular', Consolas, 'Liberation Mono', monospace"
FULL, HALF, THIRD = 830, 415, 277
INSET = 5  # transparent margin: images sit edge to edge, boards keep a 10px gap

THEMES = {
    "dark": dict(board="#0b2a1f", board2="#123d2d", copper="#c89040", pulse="#ffd27a",
                 silk="#e6efe9", chip="#16181d", text="#e1e4e8", muted="#9aa1ab",
                 pin="#b8bec7", led_off="#24272e",
                 leds=["#2a6b4a", "#3f9e67", "#5fd38c", "#a8ffc9"]),
    "light": dict(board="#e4f2ea", board2="#d0e7da", copper="#b07428", pulse="#e07b00",
                  silk="#143326", chip="#1d2026", text="#e8eaed", muted="#a3a9b2",
                  pin="#9aa1ab", led_off="#2c3038",
                  leds=["#2a6b4a", "#3f9e67", "#5fd38c", "#a8ffc9"]),
}


# ---------- data ----------

def gql(token, query):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-cards"},
    )
    with urllib.request.urlopen(req) as r:
        body = json.load(r)
    if "errors" in body:
        raise SystemExit(body["errors"])
    return body["data"]


def fetch(token):
    login = CFG["login"]
    repos = [p["repo"] for p in CFG["projects"] if not p.get("dnp")]
    aliases = "\n".join(
        f'r{i}: repository(owner: "{login}", name: "{r}") '
        "{ name description stargazerCount primaryLanguage { name color } }"
        for i, r in enumerate(repos))
    data = gql(token, f"""{{
      user(login: "{login}") {{
        login avatarUrl(size: 240)
        followers {{ totalCount }}
        repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {{
          totalCount nodes {{ stargazerCount }}
        }}
        contributionsCollection {{
          totalCommitContributions totalPullRequestContributions totalIssueContributions
          totalPullRequestReviewContributions totalRepositoryContributions
          contributionCalendar {{
          totalContributions
          weeks {{ contributionDays {{ date contributionCount }} }}
        }} }}
      }}
      {aliases}
    }}""")
    data["repos"] = {data[f"r{i}"]["name"]: data[f"r{i}"] for i in range(len(repos))}
    return data


def avatar_data_uri(url):
    req = urllib.request.Request(url, headers={"User-Agent": "profile-cards"})
    with urllib.request.urlopen(req) as r:
        mime = r.headers.get_content_type()
        return f"data:{mime};base64," + base64.b64encode(r.read()).decode()


def streaks(days):
    counts = [d["contributionCount"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    if counts and counts[-1] == 0:  # today not counted yet
        counts = counts[:-1]
    current = 0
    for c in reversed(counts):
        if not c:
            break
        current += 1
    return current, longest


# ---------- primitives ----------

def text(x, y, s, size, fill, family=SANS, weight="400", anchor="start", spacing=0, opacity=1):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" letter-spacing="{spacing}" '
            f'fill-opacity="{opacity}">{escape(str(s))}</text>')


def hole(x, y, t):
    return (f'<circle cx="{x}" cy="{y}" r="6" fill="none" stroke="{t["copper"]}" stroke-width="2.5"/>'
            f'<circle cx="{x}" cy="{y}" r="3" fill="{t["board"]}"/>')


def trace(pts, t, pulse=None):
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    ex, ey = pts[-1]
    out = (f'<path d="{d}" fill="none" stroke="{t["copper"]}" stroke-opacity="0.6" stroke-width="2" '
           f'stroke-linejoin="round"/>'
           f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="{t["board"]}" stroke="{t["copper"]}" stroke-width="2"/>')
    if pulse is not None:
        out += (f'<path d="{d}" fill="none" stroke="{t["pulse"]}" stroke-width="2.5" stroke-linecap="round" '
                f'stroke-dasharray="12 {length + 20:.0f}" stroke-dashoffset="12">'
                f'<animate attributeName="stroke-dashoffset" values="12;{-length:.0f}" dur="2.4s" '
                f'begin="{pulse:.2f}s" repeatCount="indefinite"/></path>')
    return out


def board(w, h, t, title, label, ic, content, lr=0, tb=0, dashed=False, extra_defs=""):
    """The one card template. ic = (x, y, w, h) of the IC body."""
    x, y, cw, ch = ic
    pins, traces = [], []
    for i in range(lr):
        py = y + ch * (i + 1) / (lr + 1)
        pins += [(x - 8, py - 3, 8, 6), (x + cw, py - 3, 8, 6)]
        if not dashed and i % 2 == 0:
            traces.append(trace([(x - 8, py), (x - 16, py)], t, pulse=0.7 * i))
            traces.append(trace([(x + cw + 8, py), (x + cw + 16, py)], t))
    for i in range(tb):
        px = x + cw * (i + 1) / (tb + 1)
        pins += [(px - 3, y - 8, 6, 8), (px - 3, y + ch, 6, 8)]
        if not dashed and i % 3 == 1:
            up = max(y - 22, 26)
            traces.append(trace([(px, y - 8), (px, up), (px + 10, up - 10)], t,
                                pulse=0.35 * i if i % 2 else None))
            traces.append(trace([(px, y + ch + 8), (px, y + ch + 18), (px - 10, h - 16)], t,
                                pulse=1.2 + 0.3 * i if i % 2 == 0 else None))
    pin_svg = "".join(f'<rect x="{a:.1f}" y="{b:.1f}" width="{c}" height="{d}" fill="{t["pin"]}"/>'
                      for a, b, c, d in pins)
    if dashed:
        body = (f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="5" fill="none" stroke="{t["silk"]}" '
                f'stroke-opacity="0.55" stroke-width="1.5" stroke-dasharray="7 5"/>')
    else:
        body = (f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="5" fill="{t["chip"]}"/>'
                f'<circle cx="{x + 12}" cy="{y + 12}" r="4" fill="{t["muted"]}" fill-opacity="0.5"/>')
    holes = "".join(hole(a, b, t) for a, b in ((19, 19), (w - 19, 19), (19, h - 19), (w - 19, h - 19)))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">
<title>{escape(title)}</title>
<defs>
  <linearGradient id="mask" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{t['board2']}"/><stop offset="1" stop-color="{t['board']}"/>
  </linearGradient>
  <pattern id="grid" width="16" height="16" patternUnits="userSpaceOnUse">
    <circle cx="8" cy="8" r="0.9" fill="{t['silk']}" fill-opacity="0.12"/>
  </pattern>
  {extra_defs}
</defs>
<rect x="{INSET}" y="{INSET}" width="{w - 2 * INSET}" height="{h - 2 * INSET}" rx="14" fill="url(#mask)" stroke="{t['copper']}" stroke-opacity="0.6" stroke-width="2"/>
<rect x="{INSET}" y="{INSET}" width="{w - 2 * INSET}" height="{h - 2 * INSET}" rx="14" fill="url(#grid)"/>
{holes}
{''.join(traces)}
{text(x, y - 16, label, 13, t['silk'], MONO, weight='700', spacing=1.5) if label else ''}
{pin_svg}
{body}
{content}
</svg>
"""


# ---------- cards ----------

def id_card(d, t, avatar):
    w, h = FULL, 240
    x, y, cw, ch = 44, 52, 742, 150
    u = d["user"]
    stats = [
        ("REPOS", u["repositories"]["totalCount"]),
        ("STARS", sum(n["stargazerCount"] for n in u["repositories"]["nodes"])),
        ("FOLLOWERS", u["followers"]["totalCount"]),
        ("CONTRIB/YR", u["contributionsCollection"]["contributionCalendar"]["totalContributions"]),
    ]
    sx = x + 520
    cells = []
    for i, (label, value) in enumerate(stats):
        cx, cy = sx + (i % 2) * 110, y + 58 + (i // 2) * 58
        cells.append(text(cx, cy, value, 24, t["text"], weight="700"))
        cells.append(text(cx, cy + 18, label, 11, t["muted"], MONO, spacing=1))
    content = f"""
<clipPath id="av"><rect x="{x + 22}" y="{y + 19}" width="112" height="112" rx="6"/></clipPath>
<image href="{avatar}" x="{x + 22}" y="{y + 19}" width="112" height="112" clip-path="url(#av)"/>
<rect x="{x + 22}" y="{y + 19}" width="112" height="112" rx="6" fill="none" stroke="{t['copper']}" stroke-width="1.5"/>
{text(x + 156, y + 40, '@' + u['login'], 12, t['muted'], MONO, spacing=1.5)}
{text(x + 156, y + 84, CFG['name'], 36, t['text'], weight='700')}
{text(x + 156, y + 114, CFG['title'], 17, t['copper'])}
<line x1="{sx - 22}" y1="{y + 24}" x2="{sx - 22}" y2="{y + ch - 24}" stroke="{t['muted']}" stroke-opacity="0.35"/>
{''.join(cells)}
"""
    return board(w, h, t, f"{CFG['name']} · {CFG['title']}", None, (x, y, cw, ch), content,
                 lr=3, tb=24)


def about_card(t):
    w, h = FULL, 200
    x, y, cw, ch = 44, 50, 742, 120
    items = CFG["about"]
    col = cw / len(items)
    parts = []
    for k, item in enumerate(items):
        cx, ry = x + 28 + k * col, y + 44
        org, role, years = item["lines"]
        parts.append(f'<rect x="{cx}" y="{ry - 14}" width="42" height="20" rx="3" fill="{t["copper"]}"/>')
        parts.append(text(cx + 21, ry + 1, item["tag"], 11, t["chip"], MONO, weight="700", anchor="middle", spacing=1))
        parts.append(text(cx + 54, ry + 2, org, 17, t["text"], weight="700"))
        parts.append(text(cx, ry + 30, role, 14, t["text"]))
        parts.append(text(cx, ry + 50, years, 12, t["muted"], MONO))
        if k:
            parts.append(f'<line x1="{cx - 14}" y1="{y + 22}" x2="{cx - 14}" y2="{y + ch - 22}" '
                         f'stroke="{t["muted"]}" stroke-opacity="0.3"/>')
    return board(w, h, t, "About", "ABOUT", (x, y, cw, ch), "".join(parts), lr=2, tb=24)


def contrib_card(d, t):
    """Year breakdown as segmented LED level meters."""
    w, h = HALF, 280
    x, y, cw, ch = 30, 50, w - 60, 200
    c = d["user"]["contributionsCollection"]
    rows = [("COMMITS", c["totalCommitContributions"]), ("PRS", c["totalPullRequestContributions"]),
            ("ISSUES", c["totalIssueContributions"]), ("REVIEWS", c["totalPullRequestReviewContributions"]),
            ("REPOS", c["totalRepositoryContributions"])]
    top = max(v for _, v in rows) or 1
    segs, seg_w, gap = 15, 9, 3
    parts = []
    for k, (label, v) in enumerate(rows):
        ry = y + 38 + k * 32
        parts.append(text(x + 20, ry + 5, label, 12, t["muted"], MONO, spacing=1))
        lit = 0 if v == 0 else max(1, round(segs * math.log1p(v) / math.log1p(top)))
        for s_ in range(segs):
            sx = x + 100 + s_ * (seg_w + gap)
            if s_ < lit:
                color = t["leds"][min(3, s_ * 4 // segs)]
            else:
                color = t["led_off"]
            parts.append(f'<rect x="{sx}" y="{ry - 8}" width="{seg_w}" height="16" rx="2" fill="{color}"/>')
        parts.append(text(x + cw - 20, ry + 6, v, 15, t["text"], weight="700", anchor="end"))
    return board(w, h, t, "Contributions in the last year: " + ", ".join(f"{a} {b}" for a, b in rows),
                 "CONTRIBUTIONS", (x, y, cw, ch), "".join(parts), lr=4)


def activity_card(d, t):
    w, h = HALF, 280
    x, y, cw, ch = 30, 50, w - 60, 200
    cal = d["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = cal["weeks"][-26:]
    all_days = [day for wk in cal["weeks"] for day in wk["contributionDays"]]
    peak = max((day["contributionCount"] for wk in weeks for day in wk["contributionDays"]), default=0) or 1
    current, longest = streaks(all_days)

    pitch, rad = 12.6, 4.6
    span = 25 * pitch
    x0, y0 = x + (cw - span) / 2, y + 30
    leds = []
    for c, wk in enumerate(weeks):
        for r, day in enumerate(wk["contributionDays"]):
            n = day["contributionCount"]
            fill = t["led_off"] if n == 0 else t["leds"][min(3, math.ceil(4 * n / peak) - 1)]
            glow = ' filter="url(#glow)"' if n and n >= peak * 0.75 else ""
            leds.append(f'<circle cx="{x0 + c * pitch:.1f}" cy="{y0 + r * pitch:.1f}" r="{rad}" fill="{fill}"{glow}>'
                        f'<title>{day["date"]}: {n}</title></circle>')
    stats = [("CONTRIB/YR", cal["totalContributions"]), ("STREAK", f"{current} d"), ("LONGEST", f"{longest} d")]
    cells = []
    for k, (label, value) in enumerate(stats):
        cx = x0 - rad + k * (span + 2 * rad) / 3
        cells.append(text(cx, y + 152, value, 22, t["text"], weight="700"))
        cells.append(text(cx, y + 170, label, 11, t["muted"], MONO, spacing=1))
    defs = (f'<filter id="glow" x="-1" y="-1" width="3" height="3"><feGaussianBlur stdDeviation="1.8" result="b"/>'
            f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
    content = f"""
{''.join(leds)}
{''.join(cells)}
"""
    return board(w, h, t, f"{cal['totalContributions']} contributions in the last year",
                 "ACTIVITY", (x, y, cw, ch), content, lr=4, extra_defs=defs)


def repo_card(i, proj, d, t):
    w, h = THIRD, 250
    x, y, cw, ch = 22, 42, w - 44, 166
    if proj.get("dnp"):
        content = (text(x + cw / 2, y + 78, proj["name"], 16, t["silk"], weight="700", anchor="middle", opacity=0.8)
                   + text(x + cw / 2, y + 100, "COMING SOON", 11, t["silk"], MONO, anchor="middle",
                          spacing=2, opacity=0.6))
        return board(w, h, t, f"{proj['name']} (coming soon)", None, (x, y, cw, ch), content,
                     tb=6, dashed=True)

    r = d["repos"][proj["repo"]]
    desc = proj.get("desc") or r["description"] or ""
    lang = r["primaryLanguage"] or {"name": "", "color": None}
    lines = textwrap.wrap(desc, 32)[:4]
    content = (text(x + 16, y + 34, r["name"], 15.5, t["text"], weight="700")
               + "".join(text(x + 16, y + 60 + j * 17, s, 12.5, t["muted"]) for j, s in enumerate(lines))
               + f'<circle cx="{x + 21}" cy="{y + ch - 19}" r="5" fill="{lang["color"] or t["muted"]}"/>'
               + text(x + 32, y + ch - 15, lang["name"], 12.5, t["text"])
               + text(x + cw - 16, y + ch - 15, "★ " + str(r["stargazerCount"]), 12.5, t["text"], anchor="end"))
    return board(w, h, t, f"{r['name']}: {desc}", None, (x, y, cw, ch), content, tb=6)


def pills(items, x0, y0, max_x, t):
    """Wrap items as pills starting at (x0, y0 baseline); returns svg."""
    out, px, py = [], x0, y0
    for item in items:
        pw = 18 + 7.4 * len(item)
        if px + pw > max_x and px > x0:
            px, py = x0, py + 28
        out.append(f'<rect x="{px:.1f}" y="{py - 15}" width="{pw:.1f}" height="22" rx="11" fill="{t["board"]}" '
                   f'fill-opacity="0.9" stroke="{t["copper"]}" stroke-opacity="0.7"/>')
        out.append(text(px + pw / 2, py + 0.5, item, 13, t["silk"], anchor="middle"))
        px += pw + 8
    return "".join(out)


def daughter(x, y, w, h, title, items, t):
    """Small module board plugged in by a 3-pad header on its left edge."""
    pads = "".join(f'<rect x="{x - 3}" y="{y + h / 2 - 13 + i * 10:.1f}" width="8" height="6" rx="1" fill="{t["copper"]}"/>'
                   for i in range(3))
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{t["board2"]}" '
            f'stroke="{t["copper"]}" stroke-opacity="0.7" stroke-width="1.5"/>'
            + pads
            + text(x + 18, y + 24, title.upper(), 12, t["copper"], MONO, weight="700", spacing=1.5)
            + pills(items, x + 18, y + 54, x + w - 14, t))


def stack_card(t):
    """SKILLS IC fanning out over bent traces to one daughter board per group (2 x 2)."""
    w, h = FULL, 300
    x, y, cw, ch = 50, 85, 150, 150
    groups = CFG["skills"]
    mw, mh = 228, 100
    cols, rows_y = (290, 558), (40, 180)
    # pin k -> (module column, module row) and its route; pins sit at y + ch*(k+1)/5
    py = [y + ch * (k + 1) / 5 for k in range(4)]
    mid = [ry + mh / 2 for ry in rows_y]
    routes = [
        ((0, 0), [(x + cw + 8, py[0]), (245, py[0]), (245 + py[0] - mid[0], mid[0]), (cols[0] - 3, mid[0])]),
        ((1, 0), [(x + cw + 8, py[1]), (247, py[1]), (254, 152), (532, 152), (532, mid[0] + 10),
                  (542, mid[0]), (cols[1] - 3, mid[0])]),
        ((1, 1), [(x + cw + 8, py[2]), (247, py[2]), (254, 168), (544, 168), (544, mid[1] - 6),
                  (550, mid[1]), (cols[1] - 3, mid[1])]),
        ((0, 1), [(x + cw + 8, py[3]), (245, py[3]), (245 + mid[1] - py[3], mid[1]), (cols[0] - 3, mid[1])]),
    ]
    parts = []
    for k in range(4):
        parts.append(f'<rect x="{x - 8}" y="{py[k] - 3:.1f}" width="8" height="6" fill="{t["pin"]}"/>'
                     f'<rect x="{x + cw}" y="{py[k] - 3:.1f}" width="8" height="6" fill="{t["pin"]}"/>')
    for k, ((c, r), pts) in enumerate(routes):
        parts.append(trace(pts, t, pulse=0.6 * k))
        name, items = groups[k]
        parts.append(daughter(cols[c], rows_y[r], mw, mh, name, items, t))
    parts.append(text(x + cw / 2, y + ch / 2 + 6, "SKILLS", 17, t["text"], MONO, weight="700",
                      anchor="middle", spacing=3))
    title = "Skills: " + "; ".join(f"{a}: {', '.join(b)}" for a, b in groups)
    return board(w, h, t, title, None, (x, y, cw, ch), "".join(parts))


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    d = fetch(token)
    avatar = avatar_data_uri(d["user"]["avatarUrl"])
    OUT.mkdir(exist_ok=True)
    for mode, t in THEMES.items():
        cards = {
            "id": id_card(d, t, avatar),
            "about": about_card(t),
            "activity": activity_card(d, t),
            "stack": stack_card(t),
            "contrib": contrib_card(d, t),
        }
        for i, proj in enumerate(CFG["projects"]):
            cards[f"repo-{i + 1}"] = repo_card(i, proj, d, t)
        for name, content in cards.items():
            (OUT / f"{name}-{mode}.svg").write_text(content, encoding="utf-8")
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))


if __name__ == "__main__":
    main()
