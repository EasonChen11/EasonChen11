#!/usr/bin/env python3
"""Generate PCB-themed profile cards (SVG) from GitHub data.

Usage: GITHUB_TOKEN=... python3 scripts/gen_cards.py
Reads scripts/cards.json, writes assets/<card>-{dark,light}.svg

Every card follows one template: PCB board + silkscreen refdes + one IC whose
body carries the content + copper traces from its pins to vias.
SVG widths equal their rendered width in the README (830 / 406 / 266 px),
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
FULL, HALF, THIRD = 830, 406, 266

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
        contributionsCollection {{ contributionCalendar {{
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


def board(w, h, t, title, refdes, ic, content, lr=0, tb=0, dashed=False, extra_defs=""):
    """The one card template. ic = (x, y, w, h) of the IC body."""
    x, y, cw, ch = ic
    pins, traces = [], []
    for i in range(lr):
        py = y + ch * (i + 1) / (lr + 1)
        pins += [(x - 8, py - 3, 8, 6), (x + cw, py - 3, 8, 6)]
        if not dashed and i % 2 == 0:
            traces.append(trace([(x - 8, py), (14 if x > 30 else x - 14, py)], t, pulse=0.7 * i))
            traces.append(trace([(x + cw + 8, py), (w - 14 if w - x - cw > 30 else x + cw + 14, py)], t))
    for i in range(tb):
        px = x + cw * (i + 1) / (tb + 1)
        pins += [(px - 3, y - 8, 6, 8), (px - 3, y + ch, 6, 8)]
        if not dashed and i % 3 == 1:
            up = max(y - 22, 26)
            traces.append(trace([(px, y - 8), (px, up), (px + 10, up - 10)], t,
                                pulse=0.35 * i if i % 2 else None))
            traces.append(trace([(px, y + ch + 8), (px, y + ch + 18), (px - 10, h - 12)], t,
                                pulse=1.2 + 0.3 * i if i % 2 == 0 else None))
    pin_svg = "".join(f'<rect x="{a:.1f}" y="{b:.1f}" width="{c}" height="{d}" fill="{t["pin"]}"/>'
                      for a, b, c, d in pins)
    if dashed:
        body = (f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="5" fill="none" stroke="{t["silk"]}" '
                f'stroke-opacity="0.55" stroke-width="1.5" stroke-dasharray="7 5"/>')
    else:
        body = (f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="5" fill="{t["chip"]}"/>'
                f'<circle cx="{x + 12}" cy="{y + 12}" r="4" fill="{t["muted"]}" fill-opacity="0.5"/>')
    holes = "".join(hole(a, b, t) for a, b in ((16, 16), (w - 16, 16), (16, h - 16), (w - 16, h - 16)))
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
<rect x="2" y="2" width="{w - 4}" height="{h - 4}" rx="14" fill="url(#mask)" stroke="{t['copper']}" stroke-opacity="0.6" stroke-width="2"/>
<rect x="2" y="2" width="{w - 4}" height="{h - 4}" rx="14" fill="url(#grid)"/>
{holes}
{''.join(traces)}
{text(x, y - 16, refdes, 13, t['silk'], MONO, weight='700', spacing=1.5)}
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
{text(x + 156, y + 40, CFG['part'] + ' · @' + u['login'], 12, t['muted'], MONO, spacing=1.5)}
{text(x + 156, y + 84, CFG['name'], 36, t['text'], weight='700')}
{text(x + 156, y + 114, CFG['title'], 17, t['copper'])}
<line x1="{sx - 22}" y1="{y + 24}" x2="{sx - 22}" y2="{y + ch - 24}" stroke="{t['muted']}" stroke-opacity="0.35"/>
{''.join(cells)}
"""
    return board(w, h, t, f"{CFG['name']} · {CFG['title']}", "U1 · ID", (x, y, cw, ch), content,
                 lr=3, tb=24)


def about_card(t):
    w, h = HALF, 280
    x, y, cw, ch = 30, 50, 346, 200
    rows, ry = [], y + 40
    for item in CFG["about"]:
        rows.append(f'<rect x="{x + 16}" y="{ry - 14}" width="42" height="20" rx="3" fill="{t["copper"]}"/>')
        rows.append(text(x + 37, ry + 1, item["tag"], 11, t["chip"], MONO, weight="700", anchor="middle", spacing=1))
        for j, line in enumerate(item["lines"]):
            rows.append(text(x + 70, ry + j * 17, line, 13.5 if j == 0 else 12,
                             t["text"] if j == 0 else t["muted"], SANS if j == 0 else MONO))
        ry += 44 if len(item["lines"]) > 1 else 30
    return board(w, h, t, "About", "U2 · ABOUT", (x, y, cw, ch), "".join(rows), lr=4)


def activity_card(d, t):
    w, h = HALF, 280
    x, y, cw, ch = 30, 50, 346, 200
    cal = d["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = cal["weeks"][-26:]
    all_days = [day for wk in cal["weeks"] for day in wk["contributionDays"]]
    peak = max((day["contributionCount"] for wk in weeks for day in wk["contributionDays"]), default=0) or 1
    current, longest = streaks(all_days)

    pitch, x0, y0 = 12.4, x + 20, y + 24
    leds = []
    for c, wk in enumerate(weeks):
        for r, day in enumerate(wk["contributionDays"]):
            n = day["contributionCount"]
            fill = t["led_off"] if n == 0 else t["leds"][min(3, math.ceil(4 * n / peak) - 1)]
            glow = ' filter="url(#glow)"' if n and n >= peak * 0.75 else ""
            leds.append(f'<circle cx="{x0 + c * pitch:.1f}" cy="{y0 + r * pitch:.1f}" r="4.6" fill="{fill}"{glow}>'
                        f'<title>{day["date"]}: {n}</title></circle>')
    span = 25 * pitch
    stats = [("CONTRIB/YR", cal["totalContributions"]), ("STREAK", f"{current} d"), ("LONGEST", f"{longest} d")]
    cells = []
    for k, (label, value) in enumerate(stats):
        cx = x0 + k * 112
        cells.append(text(cx, y + 150, value, 22, t["text"], weight="700"))
        cells.append(text(cx, y + 168, label, 11, t["muted"], MONO, spacing=1))
    defs = (f'<filter id="glow" x="-1" y="-1" width="3" height="3"><feGaussianBlur stdDeviation="1.8" result="b"/>'
            f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
            f'<linearGradient id="scan" x1="0" x2="1"><stop offset="0" stop-color="{t["pulse"]}" stop-opacity="0"/>'
            f'<stop offset="0.5" stop-color="{t["pulse"]}" stop-opacity="0.25"/>'
            f'<stop offset="1" stop-color="{t["pulse"]}" stop-opacity="0"/></linearGradient>')
    content = f"""
{''.join(leds)}
<rect x="{x0 - 26}" y="{y0 - 8}" width="26" height="{6 * pitch + 16:.1f}" fill="url(#scan)">
  <animate attributeName="x" values="{x0 - 26};{x0 + span}" dur="4s" repeatCount="indefinite"/>
</rect>
{''.join(cells)}
"""
    return board(w, h, t, f"{cal['totalContributions']} contributions in the last year",
                 "U3 · ACTIVITY · 26 WEEKS", (x, y, cw, ch), content, lr=4, extra_defs=defs)


def repo_card(i, proj, d, t):
    w, h = THIRD, 250
    x, y, cw, ch = 22, 50, 222, 166
    ref = f"U{4 + i}"
    if proj.get("dnp"):
        content = (text(x + cw / 2, y + 78, proj["name"], 16, t["silk"], weight="700", anchor="middle", opacity=0.8)
                   + text(x + cw / 2, y + 100, "DO NOT POPULATE", 11, t["silk"], MONO, anchor="middle",
                          spacing=2, opacity=0.6))
        return board(w, h, t, f"{proj['name']} (coming soon)", ref + " · DNP", (x, y, cw, ch), content,
                     tb=6, dashed=True)

    r = d["repos"][proj["repo"]]
    desc = proj.get("desc") or r["description"] or ""
    lang = r["primaryLanguage"] or {"name": "", "color": None}
    lines = textwrap.wrap(desc, 30)[:4]
    content = (text(x + 16, y + 34, r["name"], 15.5, t["text"], weight="700")
               + "".join(text(x + 16, y + 60 + j * 17, s, 12.5, t["muted"]) for j, s in enumerate(lines))
               + f'<circle cx="{x + 21}" cy="{y + ch - 19}" r="5" fill="{lang["color"] or t["muted"]}"/>'
               + text(x + 32, y + ch - 15, lang["name"], 12.5, t["text"])
               + text(x + cw - 16, y + ch - 15, "★ " + str(r["stargazerCount"]), 12.5, t["text"], anchor="end"))
    return board(w, h, t, f"{r['name']}: {desc}", ref, (x, y, cw, ch), content, tb=6)


def stack_card(t):
    w, h = FULL, 230
    x, y, cw, ch = 44, 50, 742, 146
    groups = CFG["skills"]
    col = cw / len(groups)
    cols = []
    for k, (name, items) in enumerate(groups):
        cx = x + 24 + k * col
        cols.append(text(cx, y + 34, name.upper(), 12, t["copper"], MONO, weight="700", spacing=1.5))
        cols.extend(text(cx, y + 60 + j * 21, item, 14.5, t["text"]) for j, item in enumerate(items))
        if k:
            cols.append(f'<line x1="{cx - 16}" y1="{y + 20}" x2="{cx - 16}" y2="{y + ch - 20}" '
                        f'stroke="{t["muted"]}" stroke-opacity="0.3"/>')
    title = "Skills: " + "; ".join(f"{a}: {', '.join(b)}" for a, b in groups)
    return board(w, h, t, title, "U7 · SKILLS", (x, y, cw, ch), "".join(cols), lr=3, tb=24)


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
        }
        for i, proj in enumerate(CFG["projects"]):
            cards[f"repo-{i + 1}"] = repo_card(i, proj, d, t)
        for name, content in cards.items():
            (OUT / f"{name}-{mode}.svg").write_text(content, encoding="utf-8")
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))


if __name__ == "__main__":
    main()
