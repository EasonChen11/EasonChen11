#!/usr/bin/env python3
"""Generate holographic profile cards (SVG) from GitHub data.

Usage: GITHUB_TOKEN=... python3 scripts/gen_cards.py
Writes assets/{id,langs}-{dark,light}.svg
"""
import base64
import json
import os
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

LOGIN = "EasonChen11"
TITLE = "Embedded / Systems Developer"
SUBTITLE = "M.S. @ National Yang Ming Chiao Tung University"
TAGS = ["Linux", "Embedded", "Networking"]
CARD_NO = "No. 0011"
# Notebook sizes include cell outputs and dwarf real code
EXCLUDE_LANGS = {"Jupyter Notebook"}
OUT = Path(__file__).resolve().parent.parent / "assets"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"
MONO = "'SFMono-Regular', Consolas, 'Liberation Mono', monospace"

QUERY = """
query($login: String!) {
  user(login: $login) {
    name login avatarUrl(size: 200) createdAt
    followers { totalCount }
    contributionsCollection { contributionCalendar { totalContributions } }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

THEMES = {
    "dark": dict(bg1="#1a1b27", bg2="#24283b", fg="#c0caf5", muted="#7982a9",
                 accent="#7aa2f7", track="#2f3549", foil=0.18, shine=0.22),
    "light": dict(bg1="#f5f7ff", bg2="#e6eaf7", fg="#1f2335", muted="#5a607a",
                  accent="#3d59a1", track="#d5daea", foil=0.22, shine=0.55),
}


def fetch(token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": LOGIN}}).encode(),
        headers={"Authorization": f"bearer {token}", "User-Agent": "profile-cards"},
    )
    with urllib.request.urlopen(req) as r:
        body = json.load(r)
    if "errors" in body:
        raise SystemExit(body["errors"])
    return body["data"]["user"]


def avatar_data_uri(url):
    req = urllib.request.Request(url, headers={"User-Agent": "profile-cards"})
    with urllib.request.urlopen(req) as r:
        mime = r.headers.get_content_type()
        return f"data:{mime};base64," + base64.b64encode(r.read()).decode()


def defs(t, w, h):
    """Shared gradients: card body, rainbow foil, moving shine, rainbow border."""
    return f"""<defs>
  <linearGradient id="body" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{t['bg1']}"/><stop offset="1" stop-color="{t['bg2']}"/>
  </linearGradient>
  <linearGradient id="foil" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{w}" y2="{h}" spreadMethod="reflect">
    <stop offset="0" stop-color="#ff6ec7"/><stop offset="0.2" stop-color="#ffd36e"/>
    <stop offset="0.4" stop-color="#6effa8"/><stop offset="0.6" stop-color="#6ed6ff"/>
    <stop offset="0.8" stop-color="#a36eff"/><stop offset="1" stop-color="#ff6ec7"/>
    <animateTransform attributeName="gradientTransform" type="translate"
      values="0 0; {w // 2} {h // 2}; 0 0" dur="8s" repeatCount="indefinite"/>
  </linearGradient>
  <linearGradient id="shine" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="{w}" y2="0" gradientTransform="rotate(20)">
    <stop offset="0.40" stop-color="#fff" stop-opacity="0"/>
    <stop offset="0.50" stop-color="#fff" stop-opacity="{t['shine']}"/>
    <stop offset="0.60" stop-color="#fff" stop-opacity="0"/>
    <animateTransform attributeName="gradientTransform" type="translate" additive="sum"
      values="-{w} 0; {w} 0" dur="5s" repeatCount="indefinite"/>
  </linearGradient>
  <pattern id="grain" width="6" height="6" patternUnits="userSpaceOnUse">
    <path d="M0 6 L6 0" stroke="{t['muted']}" stroke-opacity="0.12" stroke-width="1"/>
  </pattern>
  <clipPath id="card"><rect x="4" y="4" width="{w - 8}" height="{h - 8}" rx="18"/></clipPath>
</defs>"""


def frame(t, w, h, inner):
    return f"""<g clip-path="url(#card)">
  <rect width="{w}" height="{h}" fill="url(#body)"/>
  <rect width="{w}" height="{h}" fill="url(#grain)"/>
  <rect width="{w}" height="{h}" fill="url(#foil)" opacity="{t['foil']}"/>
  {inner}
  <rect width="{w}" height="{h}" fill="url(#shine)"/>
</g>
<rect x="4" y="4" width="{w - 8}" height="{h - 8}" rx="18" fill="none" stroke="url(#foil)" stroke-width="3"/>"""


def svg(w, h, title, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">\n'
            f"<title>{escape(title)}</title>\n{body}\n</svg>\n")


def id_card(u, t, avatar):
    w, h = 840, 320
    repos = u["repositories"]
    stars = sum(n["stargazerCount"] for n in repos["nodes"])
    stats = [
        ("REPOS", repos["totalCount"]),
        ("STARS", stars),
        ("FOLLOWERS", u["followers"]["totalCount"]),
        ("CONTRIB / YR", u["contributionsCollection"]["contributionCalendar"]["totalContributions"]),
    ]
    since = u["createdAt"][:4]
    name = escape(u["name"] or u["login"])

    tag_x, tags = 250, []
    for tag in TAGS:
        tw = 16 + 8 * len(tag)
        tags.append(
            f'<rect x="{tag_x}" y="170" width="{tw}" height="26" rx="13" fill="none" '
            f'stroke="{t["accent"]}" stroke-opacity="0.7"/>'
            f'<text x="{tag_x + tw / 2}" y="188" text-anchor="middle" font-size="13" '
            f'fill="{t["accent"]}">{escape(tag)}</text>')
        tag_x += tw + 10

    stat_w = (w - 250 - 40) / len(stats)
    cells = []
    for i, (label, value) in enumerate(stats):
        x = 250 + i * stat_w
        cells.append(
            f'<text x="{x}" y="256" font-size="26" font-weight="700" fill="{t["fg"]}">{value}</text>'
            f'<text x="{x}" y="278" font-family="{MONO}" font-size="11" letter-spacing="1.5" '
            f'fill="{t["muted"]}">{label}</text>')

    inner = f"""
  <circle cx="135" cy="160" r="88" fill="none" stroke="url(#foil)" stroke-width="4"/>
  <clipPath id="av"><circle cx="135" cy="160" r="80"/></clipPath>
  <image href="{avatar}" x="55" y="80" width="160" height="160" clip-path="url(#av)"/>
  <g font-family="{FONT}">
    <text x="250" y="62" font-family="{MONO}" font-size="12" letter-spacing="3" fill="{t['muted']}">HOLO ID · {CARD_NO} · SINCE {since}</text>
    <text x="250" y="104" font-size="38" font-weight="700" fill="{t['fg']}">{name}</text>
    <text x="250" y="134" font-size="17" fill="{t['accent']}">@{escape(u['login'])} · {escape(TITLE)}</text>
    {''.join(tags)}
    <line x1="250" y1="218" x2="{w - 40}" y2="218" stroke="{t['muted']}" stroke-opacity="0.35"/>
    {''.join(cells)}
    <text x="250" y="156" font-size="14" fill="{t['muted']}">{escape(SUBTITLE)}</text>
  </g>"""
    return svg(w, h, f"{name}'s holo ID card", defs(t, w, h) + frame(t, w, h, inner))


def langs_card(u, t, top=6):
    w, h = 840, 200
    sizes, colors = {}, {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            n = e["node"]["name"]
            if n in EXCLUDE_LANGS:
                continue
            sizes[n] = sizes.get(n, 0) + e["size"]
            colors[n] = e["node"]["color"] or "#8b949e"
    total = sum(sizes.values()) or 1
    ranked = sorted(sizes.items(), key=lambda kv: -kv[1])
    shown = ranked[:top]
    rest = sum(s for _, s in ranked[top:])
    if rest:
        shown.append(("Other", rest))
        colors["Other"] = t["muted"]

    bar_x, bar_w, x, segs = 40, w - 80, 40.0, []
    for n, s in shown:
        sw = bar_w * s / total
        segs.append(f'<rect x="{x:.1f}" y="78" width="{max(sw - 2, 1):.1f}" height="14" '
                    f'fill="{colors[n]}"><title>{escape(n)}</title></rect>')
        x += sw

    legend, col_w = [], bar_w / 4
    for i, (n, s) in enumerate(shown):
        lx, ly = bar_x + (i % 4) * col_w, 130 + (i // 4) * 30
        legend.append(
            f'<circle cx="{lx + 6}" cy="{ly - 5}" r="6" fill="{colors[n]}"/>'
            f'<text x="{lx + 20}" y="{ly}" font-size="15" fill="{t["fg"]}">{escape(n)} '
            f'<tspan fill="{t["muted"]}" font-size="13">{100 * s / total:.1f}%</tspan></text>')

    inner = f"""
  <g font-family="{FONT}">
    <text x="40" y="50" font-family="{MONO}" font-size="12" letter-spacing="3" fill="{t['muted']}">LANGUAGES · BY BYTES ACROSS OWN REPOS · EXCL. NOTEBOOKS</text>
    <clipPath id="bar"><rect x="{bar_x}" y="78" width="{bar_w}" height="14" rx="7"/></clipPath>
    <rect x="{bar_x}" y="78" width="{bar_w}" height="14" rx="7" fill="{t['track']}"/>
    <g clip-path="url(#bar)">{''.join(segs)}</g>
    {''.join(legend)}
  </g>"""
    return svg(w, h, "Most used languages", defs(t, w, h) + frame(t, w, h, inner))


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    u = fetch(token)
    avatar = avatar_data_uri(u["avatarUrl"])
    OUT.mkdir(exist_ok=True)
    for mode, t in THEMES.items():
        (OUT / f"id-{mode}.svg").write_text(id_card(u, t, avatar))
        (OUT / f"langs-{mode}.svg").write_text(langs_card(u, t))
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))


if __name__ == "__main__":
    main()
