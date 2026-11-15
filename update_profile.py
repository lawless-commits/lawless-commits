"""Regenerate dark_mode.svg / light_mode.svg: a neofetch-style profile card with live GitHub stats.

Runs daily via GitHub Actions. Standard library only.
"""
import calendar
import html
import json
import os
import urllib.request
from datetime import date, datetime, timezone

USER = "lawless-commits"
W = 56  # info column width in characters

ART = r"""
██╗      █████╗ ██╗    ██╗███████╗ █████╗
██║     ██╔══██╗██║    ██║╚════██║██╔══██╗
██║     ███████║██║ █╗ ██║    ██╔╝███████║
██║     ██╔══██║██║███╗██║   ██╔╝ ██╔══██║
███████╗██║  ██║╚███╔███╔╝   ██║  ██║  ██║
╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝    ╚═╝  ╚═╝  ╚═╝
"""
TAGLINE = "──── TECHNOLOGY SOLUTIONS ────"

# GITHUB_TOKEN (from Actions) sees public repos only. Add an ACCESS_TOKEN secret
# (a fine-grained PAT with read access to your repos) to include private repos
# in the repo count, stars and lines of code.
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("ACCESS_TOKEN") or ""
PRIV_TOKEN = os.environ.get("ACCESS_TOKEN") or TOKEN


def graphql(query, variables=None, token=None):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"Bearer {token or TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
    if resp.get("errors"):
        raise RuntimeError(resp["errors"])
    return resp["data"]


def elapsed(b, t):
    """Whole years, months and days from date b to date t."""
    years = t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    months = (t.month - b.month - (t.day < b.day)) % 12
    if t.day >= b.day:
        days = t.day - b.day
    else:
        pm_year, pm = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
        days = calendar.monthrange(pm_year, pm)[1] - b.day + t.day
    return years, months, days


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def fetch_stats():
    u = graphql(f"""
    query {{
      user(login: "{USER}") {{
        id createdAt
        followers {{ totalCount }}
        repositories(first: 100, ownerAffiliations: OWNER) {{
          totalCount
          nodes {{ name stargazerCount isFork }}
        }}
        repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) {{
          totalCount
        }}
      }}
    }}""", token=PRIV_TOKEN)["user"]
    joined = datetime.fromisoformat(u["createdAt"].replace("Z", "+00:00")).date()

    # contributionsCollection spans at most a year, so ask once per calendar year
    years = "\n".join(
        f'y{y}: contributionsCollection(from: "{y}-01-01T00:00:00Z", to: "{y + 1}-01-01T00:00:00Z")'
        " { totalCommitContributions restrictedContributionsCount }"
        for y in range(joined.year, datetime.now(timezone.utc).year + 1)
    )
    contrib = graphql(f'query {{ user(login: "{USER}") {{ {years} }} }}')["user"]

    stats = {
        "joined": joined,
        "followers": u["followers"]["totalCount"],
        "repos": u["repositories"]["totalCount"],
        "contributed": u["repositoriesContributedTo"]["totalCount"],
        "stars": sum(n["stargazerCount"] for n in u["repositories"]["nodes"]),
        "commits": sum(v["totalCommitContributions"] + v["restrictedContributionsCount"] for v in contrib.values()),
    }
    stats.update(loc([n["name"] for n in u["repositories"]["nodes"] if not n["isFork"]], u["id"]))
    return stats


LOC_QUERY = """
query($owner: String!, $name: String!, $id: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, author: {id: $id}, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { additions deletions }
      }
    } } }
  }
}"""


def loc(repo_names, user_id):
    """Sum additions/deletions of your own commits on each repo's default branch."""
    add = rem = 0
    for name in repo_names:
        cursor = None
        try:
            while True:
                ref = graphql(LOC_QUERY, {"owner": USER, "name": name, "id": user_id, "cursor": cursor},
                              token=PRIV_TOKEN)["repository"]["defaultBranchRef"]
                if ref is None:
                    break  # empty repo
                h = ref["target"]["history"]
                add += sum(n["additions"] for n in h["nodes"])
                rem += sum(n["deletions"] for n in h["nodes"])
                if not h["pageInfo"]["hasNextPage"]:
                    break
                cursor = h["pageInfo"]["endCursor"]
        except Exception as e:
            print(f"loc {name}: {e}")
    return {"loc_add": add, "loc_del": rem, "loc": add - rem}


PALETTES = {
    "dark": {"bg": "#0d1117", "border": "#30363d", "art": "#c9d1d9", "tag": "#8b949e", "h": "#58a6ff",
             "k": "#ffa657", "v": "#c9d1d9", "d": "#484f58", "g": "#3fb950", "r": "#f85149"},
    "light": {"bg": "#ffffff", "border": "#d0d7de", "art": "#24292f", "tag": "#57606a", "h": "#0969da",
              "k": "#953800", "v": "#24292f", "d": "#afb8c1", "g": "#1a7f37", "r": "#cf222e"},
}


def kv(key, val, width=W):
    dots = "." * max(width - len(key) - len(str(val)) - 3, 1)
    return [(f"{key}: ", "k"), (dots + " ", "d"), (str(val), "v")]


def kv2(k1, v1, k2, v2):
    return kv(k1, v1, 30) + [(" | ", "d")] + kv(k2, v2, 23)


def rule(title=""):
    label = f"─ {title} " if title else ""
    return [(label, "h"), ("─" * (W - len(label)), "d")]


def info_lines(s):
    y, m, d = elapsed(s["joined"], date.today())
    uptime = ", ".join(([plural(y, "year")] if y else []) + [plural(m, "month"), plural(d, "day")])
    n = lambda x: f"{x:,}"
    return [
        [(f"{USER}@github ", "h"), ("─" * (W - len(USER) - 8), "d")],
        [],
        kv("OS", "Garuda Linux"),
        kv("Uptime", uptime),
        kv("Host", "LAW7A Technology Solutions"),
        kv("Kernel", "Business major → prompt engineer"),
        kv("IDE", "Claude Code"),
        [],
        kv("Languages.Programming", "TypeScript, Go, Rust, Python"),
        kv("Mission", "Automate life as much as possible"),
        [],
        rule("Projects"),
        kv("gh-offload", "Run builds on GitHub's runners"),
        kv("botpolicy", "AI crawler policy checks in CI"),
        [],
        rule("GitHub Stats"),
        kv2("Repos", f"{s['repos']} {{Contributed: {s['contributed']}}}", "Stars", n(s["stars"])),
        kv2("Commits", n(s["commits"]), "Followers", n(s["followers"])),
        [("Lines of Code: ", "k"), (n(s["loc"]), "v"), (" ( ", "d"),
         (n(s["loc_add"]) + "++", "g"), (", ", "d"), (n(s["loc_del"]) + "--", "r"), (" )", "d")],
    ]


def render(mode, stats):
    p = PALETTES[mode]
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="460" viewBox="0 0 840 460" '
        'font-family="Consolas, Menlo, \'DejaVu Sans Mono\', monospace" font-size="13px">',
        f'<rect x="0.5" y="0.5" width="839" height="459" rx="10" fill="{p["bg"]}" stroke="{p["border"]}"/>',
    ]
    art = ART.strip("\n").split("\n")
    top = 200
    for i, line in enumerate(art):
        out.append(f'<text x="30" y="{top + i * 15}" fill="{p["art"]}" xml:space="preserve">{html.escape(line)}</text>')
    out.append(f'<text x="195" y="{top + len(art) * 15 + 18}" fill="{p["tag"]}" font-size="11px" '
               f'text-anchor="middle" xml:space="preserve">{html.escape(TAGLINE)}</text>')
    for i, segs in enumerate(info_lines(stats)):
        if not segs:
            continue
        spans = "".join(f'<tspan fill="{p[c]}">{html.escape(t)}</tspan>' for t, c in segs)
        out.append(f'<text x="390" y="{45 + i * 21}" xml:space="preserve">{spans}</text>')
    out.append("</svg>")
    return "\n".join(out)


def selfcheck():
    assert elapsed(date(2026, 5, 30), date(2026, 11, 15)) == (0, 5, 16)
    assert elapsed(date(2000, 3, 31), date(2026, 4, 1)) == (26, 0, 1)
    assert elapsed(date(2000, 1, 1), date(2026, 1, 1)) == (26, 0, 0)
    assert len("".join(t for t, _ in kv("OS", "Garuda Linux"))) == W


if __name__ == "__main__":
    selfcheck()
    stats = fetch_stats()
    print("stats:", stats)
    for mode in PALETTES:
        with open(f"{mode}_mode.svg", "w", encoding="utf-8") as f:
            f.write(render(mode, stats))
    print("wrote dark_mode.svg, light_mode.svg")
