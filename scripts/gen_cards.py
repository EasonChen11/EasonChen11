#!/usr/bin/env python3
"""Generate PCB-themed profile cards (SVG) from GitHub data.

Usage: GITHUB_TOKEN=... python3 scripts/gen_cards.py
Reads scripts/cards.json, writes assets/<card>-{dark,light}.svg
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

THEMES = {
    "dark": dict(board="#0b2a1f", board2="#123d2d", copper="#c89040", pulse="#ffd27a",
                 silk="#e6efe9", muted="#86a898", chip="#16181d", chip_text="#d7dbe0",
                 chip_muted="#8a9099", pin="#b8bec7", led_off="#17402f",
                 leds=["#2a6b4a", "#3f9e67", "#5fd38c", "#a8ffc9"]),
    "light": dict(board="#e4f2ea", board2="#d0e7da", copper="#b07428", pulse="#e07b00",
                  silk="#143326", muted="#4f7363", chip="#1d2026", chip_text="#e3e6ea",
                  chip_muted="#9aa1ab", pin="#9aa1ab", led_off="#c3dccf",
                  leds=["#9fd8b7", "#5fbf88", "#2f9e62", "#137a44"]),
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
        "{ name url description stargazerCount primaryLanguage { name color } }"
        for i, r in enumerate(repos))
    data = gql(token, f"""{{
      user(login: "{login}") {{
        login avatarUrl(size: 200)
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


# ---------- drawing primitives ----------

def svg(w, h, t, title, inner):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">
<title>{escape(title)}</title>
<defs>
  <linearGradient id="mask" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{t['board2']}"/><stop offset="1" stop-color="{t['board']}"/>
  </linearGradient>
  <pattern id="grid" width="16" height="16" patternUnits="userSpaceOnUse">
    <circle cx="8" cy="8" r="0.9" fill="{t['muted']}" fill-opacity="0.18"/>
  </pattern>
</defs>
<rect x="2" y="2" width="{w - 4}" height="{h - 4}" rx="14" fill="url(#mask)" stroke="{t['copper']}" stroke-opacity="0.6" stroke-width="2"/>
<rect x="2" y="2" width="{w - 4}" height="{h - 4}" rx="14" fill="url(#grid)"/>
{''.join(hole(x, y, t) for x, y in ((16, 16), (w - 16, 16), (16, h - 16), (w - 16, h - 16)))}
{inner}
</svg>
"""


def hole(x, y, t):
    return (f'<circle cx="{x}" cy="{y}" r="6" fill="none" stroke="{t["copper"]}" stroke-width="2.5"/>'
            f'<circle cx="{x}" cy="{y}" r="3" fill="{t["board"]}"/>')


def trace(pts, t, pulse=None):
    """Orthogonal copper trace ending in a via; pulse=delay seconds adds a moving signal."""
    d = "M" + " L".join(f"{x} {y}" for x, y in pts)
    length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    ex, ey = pts[-1]
    out = (f'<path d="{d}" fill="none" stroke="{t["copper"]}" stroke-opacity="0.55" stroke-width="2" '
           f'stroke-linejoin="round"/>'
           f'<circle cx="{ex}" cy="{ey}" r="4" fill="{t["board"]}" stroke="{t["copper"]}" stroke-width="2"/>')
    if pulse is not None:
        out += (f'<path d="{d}" fill="none" stroke="{t["pulse"]}" stroke-width="2.5" stroke-linecap="round" '
                f'stroke-dasharray="14 {length + 20:.0f}" stroke-dashoffset="14">'
                f'<animate attributeName="stroke-dashoffset" values="14;{-length:.0f}" dur="2.4s" '
                f'begin="{pulse}s" repeatCount="indefinite"/></path>')
    return out


def chip(x, y, w, h, t, lr=0, tb=0, dashed=False):
    """IC package with pins; lr / tb = pins per side. Returns svg and pin coordinates."""
    pins, out = {"l": [], "r": [], "t": [], "b": []}, []
    for i in range(lr):
        py = y + h * (i + 1) / (lr + 1)
        pins["l"].append((x - 9, py))
        pins["r"].append((x + w + 9, py))
        out.append(f'<rect x="{x - 9}" y="{py - 3}" width="9" height="6" fill="{t["pin"]}"/>'
                   f'<rect x="{x + w}" y="{py - 3}" width="9" height="6" fill="{t["pin"]}"/>')
    for i in range(tb):
        px = x + w * (i + 1) / (tb + 1)
        pins["t"].append((px, y - 9))
        pins["b"].append((px, y + h + 9))
        out.append(f'<rect x="{px - 3}" y="{y - 9}" width="6" height="9" fill="{t["pin"]}"/>'
                   f'<rect x="{px - 3}" y="{y + h}" width="6" height="9" fill="{t["pin"]}"/>')
    if dashed:
        body = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="none" stroke="{t["silk"]}" '
                f'stroke-opacity="0.55" stroke-width="1.5" stroke-dasharray="6 5"/>')
    else:
        body = (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{t["chip"]}"/>'
                f'<circle cx="{x + 12}" cy="{y + 12}" r="4" fill="{t["chip_muted"]}" fill-opacity="0.5"/>')
    return "".join(out) + body, pins


def text(x, y, s, size, fill, family=SANS, weight="400", anchor="start", spacing=0, opacity=1):
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}" letter-spacing="{spacing}" '
            f'fill-opacity="{opacity}">{escape(str(s))}</text>')


# ---------- cards ----------

def id_card(d, t, avatar):
    w, h = 640, 300
    u = d["user"]
    stats = [
        ("REPOS", u["repositories"]["totalCount"]),
        ("STARS", sum(n["stargazerCount"] for n in u["repositories"]["nodes"])),
        ("FOLLOWERS", u["followers"]["totalCount"]),
        ("CONTRIB/YR", u["contributionsCollection"]["contributionCalendar"]["totalContributions"]),
    ]
    cx, cy, cw, ch = 250, 55, 350, 195
    body, pins = chip(cx, cy, cw, ch, t, lr=6, tb=12)
    traces = []
    for i, (px, py) in enumerate(pins["t"]):
        if i % 3 == 0:
            traces.append(trace([(px, py), (px, 34), (px + 14, 22)], t, pulse=i * 0.3 if i % 2 == 0 else None))
    for i, (px, py) in enumerate(pins["b"]):
        if i % 3 == 1:
            traces.append(trace([(px, py), (px, 272), (px - 14, 284)], t, pulse=1 + i * 0.25 if i % 2 else None))
    for i, (px, py) in enumerate(pins["r"]):
        if i in (1, 4):
            traces.append(trace([(px, py), (622, py)], t, pulse=0.6 * i))
    for i, (px, py) in enumerate(pins["l"]):
        if i in (1, 4):
            traces.append(trace([(px, py), (224, py), (208, 150)], t))

    cells = []
    for i, (label, value) in enumerate(stats):
        x = cx + 24 + i * (cw - 40) / 4
        cells.append(text(x, cy + 160, value, 22, t["chip_text"], weight="700"))
        cells.append(text(x, cy + 178, label, 9, t["chip_muted"], MONO, spacing=1.2))

    inner = f"""
{''.join(traces)}
<circle cx="120" cy="150" r="84" fill="none" stroke="{t['copper']}" stroke-width="3"/>
<circle cx="120" cy="150" r="84" fill="none" stroke="{t['copper']}" stroke-width="9" stroke-opacity="0.25" stroke-dasharray="2 6"/>
<clipPath id="av"><circle cx="120" cy="150" r="74"/></clipPath>
<image href="{avatar}" x="46" y="76" width="148" height="148" clip-path="url(#av)"/>
{text(120, 258, "J1 · @" + u["login"], 11, t["silk"], MONO, anchor="middle", spacing=1)}
{text(cx, 40, "U0", 12, t["silk"], MONO, weight="700", spacing=1)}
{body}
{text(cx + 28, cy + 34, CFG["part"] + " · REV " + CFG.get("rev", "2026"), 10, t["chip_muted"], MONO, spacing=2)}
{text(cx + 24, cy + 72, CFG["name"], 32, t["chip_text"], weight="700")}
{text(cx + 24, cy + 98, CFG["title"], 14, t["copper"])}
<line x1="{cx + 24}" y1="{cy + 122}" x2="{cx + cw - 24}" y2="{cy + 122}" stroke="{t['chip_muted']}" stroke-opacity="0.35"/>
{''.join(cells)}
"""
    return svg(w, h, t, f"{CFG['name']} · {CFG['title']}", inner)


def about_card(t):
    w, h = 340, 300
    rows, y = [], 70
    bus_top = y - 14
    for item in CFG["about"]:
        rows.append(f'<rect x="40" y="{y - 13}" width="40" height="18" rx="3" fill="{t["copper"]}"/>')
        rows.append(text(60, y, item["tag"], 10, t["board"], MONO, weight="700", anchor="middle", spacing=1))
        rows.append(f'<line x1="24" y1="{y - 4}" x2="40" y2="{y - 4}" stroke="{t["copper"]}" stroke-width="2" stroke-opacity="0.55"/>')
        for j, line in enumerate(item["lines"]):
            rows.append(text(92, y + j * 17, line, 12.5 if j == 0 else 11,
                             t["silk"] if j == 0 else t["muted"], SANS if j == 0 else MONO))
        y += 56
    bus = (f'<line x1="24" y1="{bus_top}" x2="24" y2="{y - 52}" stroke="{t["copper"]}" stroke-width="2" stroke-opacity="0.55"/>'
           f'<line x1="24" y1="{bus_top}" x2="24" y2="{y - 52}" stroke="{t["pulse"]}" stroke-width="2.5" '
           f'stroke-dasharray="12 400" stroke-dashoffset="12"><animate attributeName="stroke-dashoffset" '
           f'values="12;-{y - 52 - bus_top}" dur="2.8s" repeatCount="indefinite"/></line>')
    inner = f"""
{text(40, 38, "J2 · ABOUT", 12, t["silk"], MONO, weight="700", spacing=2)}
{bus}
{''.join(rows)}
"""
    return svg(w, h, t, "About", inner)


def repo_card(i, proj, d, t):
    w, h = 320, 220
    ref = f"U{i + 1}"
    cx, cy, cw, ch = 30, 46, 260, 140
    if proj.get("dnp"):
        body, _ = chip(cx, cy, cw, ch, t, tb=8, dashed=True)
        inner = f"""
{text(cx, 32, ref + " · DNP", 12, t["silk"], MONO, weight="700", spacing=1)}
{body}
{text(w / 2, cy + 68, proj["name"], 17, t["silk"], weight="700", anchor="middle", opacity=0.75)}
{text(w / 2, cy + 92, "DO NOT POPULATE", 10, t["muted"], MONO, anchor="middle", spacing=2)}
"""
        return svg(w, h, t, f"{proj['name']} (coming soon)", inner)

    r = d["repos"][proj["repo"]]
    desc = proj.get("desc") or r["description"] or ""
    lang = r["primaryLanguage"] or {"name": "", "color": t["muted"]}
    body, pins = chip(cx, cy, cw, ch, t, tb=8)
    traces = [trace([pins["b"][k], (pins["b"][k][0], 208)], t, pulse=0.4 * k if k % 2 else None)
              for k in (1, 3, 5, 7)]
    lines = textwrap.wrap(desc, 38)[:3]
    desc_svg = "".join(text(cx + 18, cy + 58 + j * 16, s, 11.5, t["chip_muted"]) for j, s in enumerate(lines))
    inner = f"""
{text(cx, 32, ref, 12, t["silk"], MONO, weight="700", spacing=1)}
{''.join(traces)}
{body}
{text(cx + 18, cy + 34, r["name"], 17, t["chip_text"], weight="700")}
{desc_svg}
<circle cx="{cx + 24}" cy="{cy + ch - 18}" r="5" fill="{lang['color'] or t['muted']}"/>
{text(cx + 34, cy + ch - 14, lang["name"], 11, t["chip_text"])}
{text(cx + cw - 18, cy + ch - 14, "★ " + str(r["stargazerCount"]), 11, t["chip_text"], anchor="end")}
"""
    return svg(w, h, t, f"{r['name']}: {desc}", inner)


def stack_card(t):
    w, h = 480, 260
    groups = CFG["skills"]
    cx, cy, cw, ch = 34, 50, 96, 176
    body, pins = chip(cx, cy, cw, ch, t, lr=len(groups))
    rows = []
    for k, ((px, py), (name, items)) in enumerate(zip(pins["r"], groups)):
        rows.append(trace([(px, py), (164, py)], t, pulse=0.5 * k))
        rows.append(text(178, py - 4, name.upper(), 10, t["copper"], MONO, weight="700", spacing=1.5))
        rows.append(text(178, py + 13, items, 12.5, t["silk"]))
        rows.append(text(px - 18, py + 4, str(k + 1), 9, t["chip_muted"], MONO, anchor="middle"))
    inner = f"""
{text(cx, 36, "U5 · STACK", 12, t["silk"], MONO, weight="700", spacing=2)}
{body}
<text x="{cx + cw / 2}" y="{cy + ch / 2}" transform="rotate(-90 {cx + cw / 2} {cy + ch / 2})" font-family="{MONO}" font-size="13" font-weight="700" letter-spacing="4" fill="{t['chip_text']}" text-anchor="middle" dominant-baseline="middle">SKILLS</text>
{''.join(rows)}
"""
    return svg(w, h, t, "Skills: " + "; ".join(f"{a}: {b}" for a, b in groups), inner)


def activity_card(d, t):
    w, h = 480, 260
    cal = d["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = cal["weeks"][-26:]
    all_days = [day for wk in cal["weeks"] for day in wk["contributionDays"]]
    peak = max((day["contributionCount"] for wk in weeks for day in wk["contributionDays"]), default=0) or 1
    current, longest = streaks(all_days)

    pitch, x0, y0 = 15.4, 42, 64
    leds = []
    for c, wk in enumerate(weeks):
        for rr, day in enumerate(wk["contributionDays"]):
            n = day["contributionCount"]
            fill = t["led_off"] if n == 0 else t["leds"][min(3, math.ceil(4 * n / peak) - 1)]
            glow = ' filter="url(#glow)"' if n and n >= peak * 0.75 else ""
            leds.append(f'<circle cx="{x0 + c * pitch:.1f}" cy="{y0 + rr * pitch:.1f}" r="5.2" fill="{fill}"{glow}>'
                        f'<title>{day["date"]}: {n}</title></circle>')
    sweep_w = 26 * pitch
    stats = [("CONTRIB / YR", cal["totalContributions"]), ("STREAK", f"{current} d"), ("LONGEST", f"{longest} d")]
    cells = []
    for k, (label, value) in enumerate(stats):
        x = 42 + k * 140
        cells.append(text(x, 210, value, 22, t["silk"], weight="700"))
        cells.append(text(x, 228, label, 9.5, t["muted"], MONO, spacing=1.5))
    inner = f"""
<defs><filter id="glow" x="-1" y="-1" width="3" height="3"><feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<linearGradient id="scan" x1="0" x2="1"><stop offset="0" stop-color="{t['pulse']}" stop-opacity="0"/><stop offset="0.5" stop-color="{t['pulse']}" stop-opacity="0.22"/><stop offset="1" stop-color="{t['pulse']}" stop-opacity="0"/></linearGradient></defs>
{text(34, 38, "D1 · LED MATRIX · 26 WEEKS", 12, t["silk"], MONO, weight="700", spacing=2)}
<rect x="{x0 - 12}" y="{y0 - 12}" width="{sweep_w + 8}" height="{7 * pitch + 8}" rx="6" fill="{t['board']}" fill-opacity="0.55" stroke="{t['copper']}" stroke-opacity="0.4"/>
{''.join(leds)}
<rect x="{x0 - 30}" y="{y0 - 12}" width="30" height="{7 * pitch + 8}" fill="url(#scan)">
  <animate attributeName="x" values="{x0 - 30};{x0 + sweep_w - 10}" dur="4s" repeatCount="indefinite"/>
</rect>
{''.join(cells)}
"""
    return svg(w, h, t, f"{cal['totalContributions']} contributions in the last year", inner)


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
            "stack": stack_card(t),
            "activity": activity_card(d, t),
        }
        for i, proj in enumerate(CFG["projects"]):
            cards[f"repo-{i + 1}"] = repo_card(i, proj, d, t)
        for name, content in cards.items():
            (OUT / f"{name}-{mode}.svg").write_text(content, encoding="utf-8")
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))


if __name__ == "__main__":
    main()
