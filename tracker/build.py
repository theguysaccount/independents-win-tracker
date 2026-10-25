"""Render the static site from data/ into _site/.

  python3 -m tracker.build                      # -> _site/
  python3 -m tracker.build --site-url https://example.org

Every page is plain HTML that works without JavaScript. Every number printed carries its source
and the time it was read. Relative links throughout, so the same build works on a project path
(theguysaccount.github.io/independents-win-tracker/) and on a custom domain.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from html import escape

from . import graphics
from .common import (DATA, ROOT, STATES, iso, load_config, money, now_utc, ordinal, parse_iso, pct,
                     person_name, race_label, read_json, slugify, surname)
from .markets import read_history

E = escape
PARTY_SHORT = {"D": "D", "R": "R", "I": "I"}
PARTY_WORD = {"D": "Democratic", "R": "Republican", "I": "independent"}
PARTY_NOUN = {"D": "Democrats", "R": "Republicans"}
PARTY_MEMBER = {"D": "Democrat", "R": "Republican", "I": "independent"}
VENUE = {"kalshi": "Kalshi", "polymarket": "Polymarket"}
LOGO = ('<svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="#5a3fd1"/>'
        '<path d="M5 12.5h22" stroke="#fff" stroke-width="2.6" stroke-linecap="round"/><path d="M16 13.5l-6 11h12z" fill="#fff"/>'
        '<circle cx="7.5" cy="9" r="2.4" fill="#fff"/><circle cx="24.5" cy="9" r="2.4" fill="#fff"/></svg>')


# ---------------------------------------------------------------- small formatters

def fmt_dt(s):
    """'2026-10-25T21:00:00Z' -> 'Oct. 25, 2026, 21:00 UTC'."""
    d = parse_iso(s) if isinstance(s, str) else s
    if not d:
        return "unknown time"
    return f"{fmt_date(d.date())}, {d.strftime('%H:%M')} UTC"


_AP_MONTHS = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]


def fmt_date(d):
    """AP style: 'Oct. 25, 2026', 'March 9, 2026'."""
    if isinstance(d, str):
        if not d:
            return "unknown date"
        d = date.fromisoformat(d[:10])
    return f"{_AP_MONTHS[d.month - 1]} {d.day}, {d.year}"


def http_date_to_iso(s):
    try:
        return datetime.strptime(s, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return ""


def tm(s, text=None):
    d = parse_iso(s) if isinstance(s, str) else s
    if not d:
        return E(text or "unknown")
    return f'<time datetime="{iso(d)}">{E(text or fmt_dt(d))}</time>'


def a_out(url, text, kind="link"):
    if not url:
        return E(text)
    return f'<a href="{E(url)}" rel="noopener" data-out="{E(kind)}">{E(text)}</a>'


def chip(party, text=None):
    cls = party if party in ("D", "R", "I") else "plain"
    return f'<span class="chip {cls}">{E(text or party)}</span>'


def change_html(delta):
    if delta is None:
        return '<span class="muted">—</span>'
    pts = delta * 100
    if abs(pts) < 0.05:
        return '<span class="muted">±0</span>'
    cls = "up" if pts > 0 else "down"
    return f'<span class="{cls}">{"▲" if pts > 0 else "▼"} {abs(pts):.1f}</span>'


# ---------------------------------------------------------------- the model

class Model:
    def __init__(self, cfg, fec, mk, votes, rollcalls, status, hist, now):
        self.cfg, self.fec, self.mk, self.votes, self.rc = cfg, fec or {}, mk or {}, votes or {}, rollcalls or {}
        self.status, self.hist, self.now = status or {}, hist, now
        self.members = (self.votes or {}).get("members", [])
        self.member_by_fec = {fid: m for m in self.members for fid in m.get("fec_ids", [])}
        self.candidates = self._candidates()

    # -- markets per candidate
    def _candidates(self):
        fec = self.fec
        cands = fec.get("candidates", {})
        slate = set(self.cfg.get("slate", {}).get("fec_ids", []))
        exclude = self.cfg.get("exclude", {})
        linked = {}
        for rec in self.mk.get("races", []):
            for o in rec["outcomes"]:
                cid = o.get("cand_id") if (o.get("cand_id") in cands and cands[o["cand_id"]]["independent"]) else o.get("covers")
                if cid and cid in cands:
                    linked.setdefault(cid, []).append((rec, o))
        ids = [cid for cid in set(linked) | (slate & set(cands)) if cid not in exclude]
        out, used = [], set()
        for cid in ids:
            c = cands[cid]
            venues = {}
            for rec, o in linked.get(cid, []):
                kind = "candidate" if o.get("cand_id") == cid else "party"
                cur = venues.get(rec["source"])
                if cur is None or (cur["kind"] == "party" and kind == "candidate"):
                    venues[rec["source"]] = {"rec": rec, "o": o, "kind": kind}
            name = c["name"]
            for src in ("kalshi", "polymarket"):
                v = venues.get(src)
                if v and v["kind"] == "candidate":
                    name = re.sub(r"\s*\([^)]*\)\s*$", "", v["o"]["label"]).strip() or name
                    break
            prices = [v["o"]["price"] for v in venues.values() if v["o"].get("price") is not None]
            slug = slugify(name)
            if slug in used:
                slug = slugify(f"{name} {c['state']}")
            used.add(slug)
            race_recs = [r for r in self.mk.get("races", []) if r["race"] == c["race"]]
            out.append({
                **c, "display": name, "slug": slug, "slate": cid in slate, "venues": venues,
                "best": max(prices) if prices else None, "race_markets": race_recs,
                "member": self.member_by_fec.get(cid),
            })
        out.sort(key=lambda x: (-(x["best"] if x["best"] is not None else -1), -x["receipts"]))
        return out

    def change_24h(self, source, market_id, current):
        """Price change against the point closest to 24 hours ago (within 6 hours), from history."""
        if current is None:
            return None
        target = self.now - timedelta(hours=24)
        best, best_gap = None, timedelta(hours=3)
        for r in self.hist:
            if r["source"] != source or r["market"] != market_id:
                continue
            t = parse_iso(r["ts"])
            if t and abs(t - target) <= best_gap:
                best, best_gap = float(r["price"]), abs(t - target)
        return None if best is None else round(current - best, 4)

    def delta(self, src, o):
        """24-hour change: from stored hourly reads, else the platform's own previous-day figure."""
        d = self.change_24h(src, o["id"], o.get("price"))
        if d is None and o.get("price") is not None:
            if src == "kalshi" and o.get("prev_price") is not None:
                d = round(o["price"] - o["prev_price"], 4)
            elif src == "polymarket" and o.get("day_change") is not None:
                d = o["day_change"]
        return d

    def race_money(self, c):
        """Candidates in this race that its markets list (plus the independent), with FEC money."""
        cands = self.fec.get("candidates", {})
        rows = {}
        for rec in c["race_markets"]:
            for o in rec["outcomes"]:
                cid = o.get("cand_id")
                if cid and cid in cands:
                    party = self.party_of(cid, o, rec)
                    rows.setdefault(cid, {"cid": cid, "name": re.sub(r"\s*\([^)]*\)\s*$", "", o["label"]), "party": party})
        for cid in self.fec.get("races", {}).get(c["race"], []):
            if cands[cid]["independent"] and cid in {x["id"] for x in self.candidates} and cid not in rows:
                x = next(x for x in self.candidates if x["id"] == cid)
                rows[cid] = {"cid": cid, "name": x["display"], "party": "I"}
        out = []
        for r in rows.values():
            f = cands[r["cid"]]
            out.append({**r, "fec": f})
        out.sort(key=lambda r: -r["fec"]["receipts"])
        return out

    def party_of(self, cid, o=None, rec=None):
        f = self.fec["candidates"][cid]
        if f["party"] in ("DEM", "DFL"):
            return "D"
        if f["party"] == "REP":
            return "R"
        if f["independent"]:
            return "I"
        if rec and rec["source"] == "kalshi" and o:
            suf = o["id"].rsplit("-", 1)[-1]
            if suf in ("D", "R"):
                return suf
        if o:
            m = re.search(r"\((D|R|I)\)\s*$", o.get("label", ""))
            if m:
                return m.group(1)
        return f["party_label"]

    def agg(self, source, prefix):
        for a in self.mk.get("aggregates", []):
            if a["source"] == source and a["id"].startswith(prefix):
                return a
        return None


# ---------------------------------------------------------------- page shell

class Site:
    def __init__(self, out, site_url, cfg, model, env):
        self.out, self.url, self.cfg, self.m, self.env = out, site_url.rstrip("/"), cfg, model, env
        self.pages = []  # (path, lastmod, priority)
        css = open(os.path.join(ROOT, "static", "style.css"), "rb").read()
        js = open(os.path.join(ROOT, "static", "app.js"), "rb").read()
        self.ver = hashlib.sha1(css + js).hexdigest()[:10]

    def abs(self, path):
        return f"{self.url}/{path}"

    def write(self, path, content, binary=False):
        full = os.path.join(self.out, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as f:
            f.write(content)

    def page(self, path, title, desc, body, *, nav="", og="og/home.png", jsonld=None, crumbs=None,
             lastmod=None, priority="0.6", index=True):
        """path: 'candidates/dan-osborn/' (directory pages) or '404.html'."""
        depth = path.count("/")
        root = "../" * depth if depth else "./"
        if path == "404.html":  # served at any depth, so it needs absolute links
            from urllib.parse import urlparse
            root = urlparse(self.url).path.rstrip("/") + "/"
        canonical = self.abs(path)
        crumbs_html = ""
        ld = list(jsonld or [])
        if crumbs:
            parts = [f'<a href="{root}">Home</a>'] + [
                (f'<a href="{root}{p}">{E(t)}</a>' if p is not None else E(t)) for t, p in crumbs]
            crumbs_html = f'<div class="crumbs">{" › ".join(parts)}</div>'
            items = [{"@type": "ListItem", "position": 1, "name": "Home", "item": self.abs("")}]
            for i, (t, p) in enumerate(crumbs, 2):
                items.append({"@type": "ListItem", "position": i, "name": t, "item": self.abs(p if p is not None else path)})
            ld.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items})
        ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
        gc = self.env.get("GOATCOUNTER_URL", "").strip()
        gc_html = f'<script data-goatcounter="{E(gc)}" async src="https://gc.zgo.at/count.js"></script>' if gc.startswith("https://") else ""
        navs = [("candidates/", "Candidates"), ("party-line/", "Party-line index"), ("methodology/", "Methodology"),
                ("data/", "Data"), ("about/", "About")]
        current = ' aria-current="page"'
        nav_html = "".join(f'<a href="{root}{p}"{current if nav == p else ""}>{t}</a>' for p, t in navs)
        og_url = self.abs(og)
        html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(desc)}">
{'<link rel="canonical" href="' + E(canonical) + '">' if index else '<meta name="robots" content="noindex">'}
<meta property="og:type" content="website">
<meta property="og:site_name" content="Independents Tracker">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{E(canonical)}">
<meta property="og:image" content="{E(og_url)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#5a3fd1">
<link rel="icon" href="{root}static/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{root}static/style.css?v={self.ver}">
<link rel="alternate" type="application/atom+xml" title="Independents Tracker: daily odds" href="{root}feed.xml">
{ld_html}
{gc_html}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="site"><div class="wrap">
<a class="brand" href="{root}">{LOGO}<span>Independents Tracker</span></a>
<nav class="main" aria-label="Main">{nav_html}</nav>
</div></header>
<main id="main"><div class="wrap">
{crumbs_html}
{body}
</div></main>
{self.footer(root)}
<script src="{root}static/app.js?v={self.ver}" defer></script>
</body></html>
"""
        self.write(path + ("index.html" if path.endswith("/") or path == "" else ""), html)
        if index:
            self.pages.append((path, lastmod or iso(self.m.now)[:10], priority))

    def footer(self, root):
        st = self.m.status
        mk = self.m.mk.get("fetched_at")
        fec_lm = http_date_to_iso(self.m.fec.get("source", {}).get("weball", {}).get("last_modified", ""))
        vv_last = max((c.get("last_date", "") for c in self.m.votes.get("chambers", {}).values()), default="")
        support = self.env.get("SUPPORT_URL", "").strip()
        support_label = self.env.get("SUPPORT_LABEL", "").strip() or "Support this tracker"
        support_html = (f'<p><a href="{E(support)}" rel="noopener sponsored">{E(support_label)}</a>. '
                        "Support pays for upkeep only; it is not a political contribution and goes to no candidate.</p>"
                        if support.startswith("https://") else "")
        return f"""<footer class="site"><div class="wrap cols">
<div><strong>Independents Tracker</strong><p>A neutral, sourced tracker of independent candidates for Congress and of party-line voting in Congress. No endorsements. Not affiliated with any candidate, campaign, party, PAC or prediction market.</p>{support_html}</div>
<div><strong>Data as of</strong><p class="asof">Markets (Kalshi, Polymarket): {tm(mk)}<br>FEC bulk file: {tm(fec_lm) if fec_lm else 'unknown'}<br>Roll calls (Voteview): through {E(fmt_date(vv_last)) if vv_last else 'unknown'}</p></div>
<div><strong>More</strong><p><a href="{root}methodology/">Methodology</a> · <a href="{root}data/">Download the data</a> · <a href="{root}about/">About and corrections</a> · <a href="{root}feed.xml">Daily feed</a> · <a href="https://github.com/{E(self.cfg['site']['repo'])}" rel="noopener">Source code</a></p>
<p class="tiny">Prediction-market prices are what traders pay, not polls or forecasts, and thin markets move on small trades. Nothing here is financial, legal or voting advice.</p></div>
</div></footer>"""


# ---------------------------------------------------------------- fragments

def venue_card(site, c, src, depth):
    v = c["venues"].get(src)
    m = site.m
    if not v:
        return (f'<div class="card"><div class="venue {src}">{VENUE[src]}</div><div class="kpi"><small>No market</small></div>'
                f'<p class="small muted">No {VENUE[src]} market listed {E(c["display"])} or an independent in this race as of {tm(m.mk.get("fetched_at"))}.</p></div>')
    rec, o = v["rec"], v["o"]
    ch = m.delta(src, o)
    resolved = o.get("result") in ("yes", "no")
    vol = o.get("volume") or 0
    thin = vol < m.cfg["markets"].get("thin_market_volume_usd", 25000)
    q = o.get("question") or rec["title"]
    kind_note = ("" if v["kind"] == "candidate" else
                 f'<p class="small">This market asks whether <em>any</em> independent wins the race, and {E(c["display"])} is the only independent in this race who has reported more than $100,000 to the FEC.</p>')
    book = []
    if o.get("bid") is not None:
        book.append(f"bid {o['bid'] * 100:.1f}¢")
    if o.get("ask") is not None:
        book.append(f"ask {o['ask'] * 100:.1f}¢")
    if o.get("last") is not None:
        book.append(f"last trade {o['last'] * 100:.1f}¢")
    stale = " (this read failed; showing the last good price)" if rec.get("stale") else ""
    return f"""<div class="card">
<div class="venue {src}">{VENUE[src]}</div>
<div class="kpi">{'Resolved ' + o['result'].upper() if resolved else pct(o.get('price'))} <small>{'' if resolved else 'implied chance'}</small></div>
<p class="small">{'' if resolved else '24h change: ' + change_html(ch) + ' pts · '}{' · '.join(book)}</p>
<p class="small muted">“{E(q)}”</p>
{kind_note}
{'<p class="note">Thin market: under $' + f"{m.cfg['markets'].get('thin_market_volume_usd', 25000):,}" + ' traded in total, so small trades can move this price a lot.</p>' if thin and not resolved else ''}
<p class="src">Source: {a_out(rec['url'], VENUE[src] + ' market ' + (rec.get('series') or rec['id']), src)}, contract {E(o['id'])}. Total volume {money(vol) if src == 'polymarket' else f'{vol:,.0f} contracts'}. Read {tm(m.mk.get('fetched_at'))}{stale}.</p>
</div>"""


def money_block(site, c):
    f = c
    as_of = http_date_to_iso(site.m.fec.get("source", {}).get("weball", {}).get("last_modified", ""))
    url = f"https://www.fec.gov/data/candidate/{f['id']}/?cycle={site.m.fec.get('cycle', 2026)}&election_full=false"
    items = [("Raised", f["receipts"], "Total receipts, 2025–26"), ("From individuals", f["indiv"], "Itemized and unitemized"),
             ("From the candidate", f["self"], "Contributions plus loans"), ("Spent", f["disb"], "Total disbursements"),
             ("Cash on hand", f["coh"], "End of the latest report"), ("Debts", f["debts"], "Owed by the campaign")]
    cells = "".join(f'<div class="card"><div class="small muted">{E(k)}</div><div class="kpi">{money(v)}</div><div class="tiny">{E(n)}</div></div>' for k, v, n in items)
    return f"""<div class="grid three">{cells}</div>
<p class="src">Source: {a_out(url, 'FEC candidate summary ' + f['id'], 'fec')} (bulk file weball{str(site.m.fec.get('cycle', 2026))[2:]}), reports through {E(fmt_date(f['cvg_end']))}; file published {tm(as_of) if as_of else 'unknown'}. Figures cover the 2025–26 two-year period and include only what the campaign itself reported.</p>"""


def race_money_table(site, c):
    rows = site.m.race_money(c)
    if len(rows) < 2:
        return ""
    body = []
    for r in rows:
        f = r["fec"]
        is_me = r["cid"] == c["id"]
        name = E(r["name"])
        if is_me:
            name = f"<strong>{name}</strong>"
        else:
            other = next((x for x in site.m.candidates if x["id"] == r["cid"]), None)
            if other:
                name = f'<a href="../{other["slug"]}/">{name}</a>'
        p = r["party"]
        body.append(f'<tr><td>{name}</td><td>{chip(p if p in ("D", "R", "I") else "plain", p)}</td>'
                    f'<td class="r num" data-v="{f["receipts"]}">{money(f["receipts"])}</td>'
                    f'<td class="r num" data-v="{f["coh"]}">{money(f["coh"])}</td>'
                    f'<td class="r num hide-sm">{E(fmt_date(f["cvg_end"]))}</td></tr>')
    return f"""<h2>Money in this race</h2>
<p class="small muted">Candidates the race's prediction markets list, with what each campaign reported to the FEC.</p>
<div class="table-wrap"><table data-sort><thead><tr><th><button>Candidate</button></th><th>Party</th><th class="r" data-type="num"><button>Raised</button></th><th class="r" data-type="num"><button>Cash on hand</button></th><th class="r hide-sm">Reports through</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></div>
<p class="src">Source: FEC candidate summaries (bulk file weball26). Party labels from the FEC, or from the market where the FEC record has none.</p>"""


def race_markets_table(site, c):
    out = []
    for rec in c["race_markets"]:
        rows = "".join(
            f'<tr><td>{E(o["label"])}</td><td class="r num">{("Resolved " + o["result"].upper()) if o.get("result") else pct(o.get("price"))}</td></tr>'
            for o in rec["outcomes"])
        out.append(f'<div class="card"><div class="venue {rec["source"]}">{VENUE[rec["source"]]}</div><h3>{E(rec["title"])}</h3>'
                   f'<div class="table-wrap"><table><thead><tr><th>Outcome</th><th class="r">Implied chance</th></tr></thead><tbody>{rows}</tbody></table></div>'
                   f'<p class="src">Source: {a_out(rec["url"], VENUE[rec["source"]] + " " + (rec.get("series") or rec["id"]), rec["source"])}; read {tm(site.m.mk.get("fetched_at"))}.</p></div>')
    if not out:
        return ""
    return '<h2>The whole race, as the markets price it</h2><div class="grid two">' + "".join(out) + "</div>"


def chart_block(site, c):
    series = []
    for src, color in (("kalshi", "--kalshi"), ("polymarket", "--poly")):
        v = c["venues"].get(src)
        if v:
            pts = graphics.history_points(site.m.hist, src, v["o"]["id"])
            series.append((VENUE[src], color, pts))
    svg = graphics.price_chart(series, site.m.now, title=f"{c['display']}: implied chance of winning, by market")
    if not svg:
        return ""
    legend = "".join(f'<span><i style="background:var({col})"></i>{E(lbl)}</span>' for lbl, col, pts in series if pts)
    return f"""<h2>Odds over time</h2>
<div class="card">{svg}<div class="legend">{legend}</div>
<p class="src">Daily closing prices from each platform's price-history endpoint, then this tracker's hourly reads for the last 14 days. Stored in <a href="https://github.com/{E(site.cfg['site']['repo'])}/blob/main/data/history.csv" rel="noopener">data/history.csv</a>.</p></div>"""


def embed_block(site, page_url, badge_url, alt, ident):
    snippet = f'<a href="{page_url}"><img src="{badge_url}" alt="{E(alt)}" height="20"></a>'
    return f"""<h2>Embed this</h2>
<p class="small muted">A live badge that updates with the data. Paste it into any web page, newsletter template or README.</p>
<p><img src="{E(badge_url)}" alt="{E(alt)}" height="20"></p>
<textarea class="code" id="embed-{ident}" readonly aria-label="Embed code">{E(snippet)}</textarea>
<p><button class="btn" data-copy="#embed-{ident}">Copy embed code</button></p>"""


def share_block(page_url, text):
    from urllib.parse import quote
    return f"""<div class="share">
<button class="btn primary" data-share="{E(page_url)}" data-text="{E(text)}">Share</button>
<a class="btn" href="https://bsky.app/intent/compose?text={quote(text + ' ' + page_url)}" rel="noopener" target="_blank">Bluesky</a>
<a class="btn" href="https://twitter.com/intent/tweet?text={quote(text)}&url={quote(page_url)}" rel="noopener" target="_blank">X</a>
<a class="btn" href="https://www.facebook.com/sharer/sharer.php?u={quote(page_url)}" rel="noopener" target="_blank">Facebook</a>
<a class="btn" href="https://www.linkedin.com/sharing/share-offsite/?url={quote(page_url)}" rel="noopener" target="_blank">LinkedIn</a>
</div>"""


def party_phrase(c):
    lbl = c["party_label"]
    if c["party"] == "IND":
        return "as an independent"
    return f"with the party label “{lbl}”"


# ---------------------------------------------------------------- pages

def candidate_page(site, c):
    m = site.m
    path = f"candidates/{c['slug']}/"
    race_long = race_label(c["state"], c["office"], c["district"])
    race_short = race_label(c["state"], c["office"], c["district"], short=True)
    k, p = c["venues"].get("kalshi"), c["venues"].get("polymarket")
    odds_bits = []
    if k:
        odds_bits.append(f"Kalshi {pct(k['o'].get('price'))}")
    if p:
        odds_bits.append(f"Polymarket {pct(p['o'].get('price'))}" + (" (any independent)" if p["kind"] == "party" else ""))
    odds_txt = ", ".join(odds_bits) if odds_bits else "no prediction market lists this candidate"
    office_word = "U.S. Senate" if c["office"] == "S" else "U.S. House"
    title = f"{c['display']} odds and money: {race_short} 2026 | Independents Tracker"
    desc = (f"{c['display']} ({c['party_label']}, {race_short}) in the 2026 election: {odds_txt}. "
            f"FEC: {money(c['receipts'])} raised, {money(c['coh'])} cash on hand through {fmt_date(c['cvg_end'])}. Sourced and updated hourly.")
    summary = [f"{E(c['display'])} is running for {E(race_long)} in the Nov. 3, 2026 general election and filed with the FEC {E(party_phrase(c))}."]
    if k:
        summary.append(f"As of {tm(m.mk.get('fetched_at'))}, Kalshi prices {E(c['display'])}’s chance of winning at <strong>{pct(k['o'].get('price'))}</strong>.")
    if p:
        if p["kind"] == "candidate":
            summary.append(f"Polymarket prices it at <strong>{pct(p['o'].get('price'))}</strong>.")
        else:
            summary.append(f"Polymarket’s market on whether an independent wins the race is at <strong>{pct(p['o'].get('price'))}</strong>.")
    if not k and not p:
        summary.append(f"Neither Kalshi nor Polymarket lists {E(c['display'])} in a market for this race as of {tm(m.mk.get('fetched_at'))}.")
    summary.append(f"The campaign has reported raising <strong>{money(c['receipts'])}</strong> and had <strong>{money(c['coh'])}</strong> in cash on hand through {E(fmt_date(c['cvg_end']))}.")
    tags = [chip("I", c["party_label"]), chip("plain", {"I": "Incumbent", "C": "Challenger", "O": "Open seat"}.get(c["ici"], "Candidate"))]
    slate_cfg = site.cfg.get("slate", {})
    if c["slate"]:
        tags.append(chip("plain", slate_cfg.get("label", "Slate")))
    member_html = ""
    mem = c.get("member")
    if mem:
        sp = mem["spells"][-1]
        member_html = (f'<div class="callout">{E(c["display"])} serves in the {E(mem["chamber"])} now. '
                       f'<a href="../../party-line/{mem["slug"]}/">Party-line voting record</a>: votes with the '
                       f'{E(PARTY_WORD.get(sp["own"], ""))} majority on {pct(sp["score"])} of party-line votes'
                       f'{" as an independent" if sp["party"] == "I" else ""} (Voteview, through {E(fmt_date(sp["last"]))}).</div>')
    slate_html = ""
    if c["slate"]:
        slate_html = (f'<p class="small muted">Named to the {E(slate_cfg.get("name", ""))} presented at the Independent National Convention '
                      f'(Sept. 23–25, 2026). Source: {a_out(slate_cfg.get("source_url"), slate_cfg.get("source_name", "source"), "slate")}. '
                      "Listed as a matter of record, not as an endorsement.</p>")
    page_url = site.abs(path)
    badge_url = site.abs(f"badge/{c['slug']}.svg")
    share_text = f"{c['display']} ({race_short}): {odds_txt}; {money(c['receipts'])} raised."
    jsonld = [{
        "@context": "https://schema.org", "@type": "ProfilePage", "name": title, "url": page_url,
        "dateModified": m.mk.get("fetched_at") or iso(m.now), "description": desc,
        "mainEntity": {"@type": "Person", "name": c["display"],
                       "description": f"{c['party_label']} candidate for {office_word}, {STATES.get(c['state'], c['state'])}, 2026"},
        "isPartOf": {"@type": "WebSite", "name": "Independents Tracker", "url": site.abs("")},
    }]
    body = f"""<h1>{E(c['display'])}</h1>
<p class="lede">{E(c['party_label'])} candidate for {E(race_long)} · general election Tuesday, Nov. 3, 2026</p>
<p>{' '.join(tags)}</p>
<p>{' '.join(summary)}</p>
{slate_html}
{member_html}
<h2>Prediction markets</h2>
<div class="grid two">{venue_card(site, c, 'kalshi', 2)}{venue_card(site, c, 'polymarket', 2)}</div>
{chart_block(site, c)}
{race_markets_table(site, c)}
<h2>Campaign money</h2>
{money_block(site, c)}
{race_money_table(site, c)}
{embed_block(site, page_url, badge_url, f"{c['display']} odds and money, Independents Tracker", c['slug'])}
<h2>Share</h2>
{share_block(page_url, share_text)}
<p class="small muted">How these numbers are made: <a href="../../methodology/">methodology</a>. Something wrong? <a href="https://github.com/{E(site.cfg['site']['repo'])}/issues/new?title={E('Correction: ' + c['display'])}" rel="noopener">Report a correction</a>.</p>"""
    og = f"og/c-{c['slug']}.png"  # tracker.og renders it, or copies the default card
    site.page(path, title, desc, body, nav="candidates/", og=og, jsonld=jsonld,
              crumbs=[("Candidates", "candidates/"), (c["display"], None)], priority="0.9")
    # badge
    vals = []
    if k:
        vals.append(f"Kalshi {pct(k['o'].get('price'))}")
    if p and p["kind"] == "candidate":
        vals.append(f"Polymarket {pct(p['o'].get('price'))}")
    value = " · ".join(vals) if vals else f"raised {money(c['receipts'])}"
    asof = parse_iso(m.mk.get("fetched_at")) or m.now
    site.write(f"badge/{c['slug']}.svg", graphics.badge(f"{c['display']} ({race_short})", f"{value} · {asof.strftime('%b')} {asof.day}",
                                                         f"{c['display']}: {value}, as of {fmt_dt(asof)}"))


def candidates_page(site):
    m = site.m
    rows = []
    for c in m.candidates:
        k, p = c["venues"].get("kalshi"), c["venues"].get("polymarket")
        kp = k["o"].get("price") if k else None
        pp = p["o"].get("price") if p else None
        rows.append(f"""<tr data-slate="{'yes' if c['slate'] else 'no'}" data-office="{c['office']}">
<td><a href="{c['slug']}/">{E(c['display'])}</a>{' <span class="chip plain">' + E(site.cfg['slate'].get('label', '')) + '</span>' if c['slate'] else ''}<div class="tiny">{E(c['party_label'])}</div></td>
<td>{E(race_label(c['state'], c['office'], c['district'], short=True))}</td>
<td class="r num" data-v="{'' if kp is None else kp}">{pct(kp) if kp is not None else '—'}</td>
<td class="r num" data-v="{'' if pp is None else pp}">{(pct(pp) + ('*' if p['kind'] == 'party' else '')) if pp is not None else '—'}</td>
<td class="r num" data-v="{c['receipts']}">{money(c['receipts'])}</td>
<td class="r num hide-sm" data-v="{c['coh']}">{money(c['coh'])}</td></tr>""")
    min_listed = site.cfg["fec"].get("min_receipts_listed", 5000)
    tracked_ids = {c["id"] for c in m.candidates}
    others = sorted([c for c in m.fec.get("candidates", {}).values()
                     if c["independent"] and c["receipts"] >= min_listed and c["id"] not in tracked_ids],
                    key=lambda c: -c["receipts"])
    orow = "".join(f"""<tr data-office="{c['office']}"><td>{E(c['name'])}</td><td>{E(race_label(c['state'], c['office'], c['district'], short=True))}</td>
<td>{E(c['party_label'])}</td><td class="r num" data-v="{c['receipts']}">{money(c['receipts'])}</td><td class="r num hide-sm" data-v="{c['coh']}">{money(c['coh'])}</td>
<td class="r hide-sm">{E(fmt_date(c['cvg_end']))}</td><td>{a_out(f"https://www.fec.gov/data/candidate/{c['id']}/?cycle=2026&election_full=false", c['id'], 'fec')}</td></tr>""" for c in others)
    body = f"""<h1>Independent candidates for Congress, 2026</h1>
<p class="lede">Every independent or no-party candidate for the U.S. House or Senate whom Kalshi or Polymarket lists in a 2026 race, with live odds and FEC money. Sorted by the higher of the two market prices.</p>
<div class="filters"><input type="search" placeholder="Filter by name or state" data-filter="#tracked" aria-label="Filter candidates">
<select data-filter="#tracked" data-key="office" aria-label="Chamber"><option value="">House and Senate</option><option value="S">Senate</option><option value="H">House</option></select>
<select data-filter="#tracked" data-key="slate" aria-label="Slate"><option value="">All candidates</option><option value="yes">{E(site.cfg['slate'].get('label', ''))} only</option></select>
<span class="small muted"><span data-count="#tracked">{len(m.candidates)}</span> shown</span></div>
<div class="table-wrap"><table id="tracked" data-sort><thead><tr><th><button>Candidate</button></th><th><button>Race</button></th>
<th class="r" data-type="num"><button>Kalshi</button></th><th class="r" data-type="num"><button>Polymarket</button></th>
<th class="r" data-type="num"><button>Raised</button></th><th class="r hide-sm" data-type="num"><button>Cash</button></th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="src">Markets read {tm(m.mk.get('fetched_at'))}. * Polymarket's market asks whether any independent wins that race. Money: FEC candidate summaries, 2025–26. The {E(site.cfg['slate'].get('label', ''))} tag marks the seven candidates presented at the Independent National Convention (<a href="{E(site.cfg['slate'].get('source_url', ''))}" rel="noopener">source</a>); it is a record, not an endorsement.</p>
<h2 id="filers">Other independent filers</h2>
<p class="small muted">{len(others)} more 2026 House and Senate candidates filed with the FEC under an independent or no-party label and reported at least ${min_listed:,}. FEC registration does not mean a candidate is on the November ballot, and no prediction market lists them; check the state's election office for ballot status.</p>
<div class="filters"><input type="search" placeholder="Filter by name or state" data-filter="#filers-table" aria-label="Filter filers"></div>
<div class="table-wrap"><table id="filers-table" data-sort><thead><tr><th><button>Candidate</button></th><th><button>Race</button></th><th><button>FEC label</button></th>
<th class="r" data-type="num"><button>Raised</button></th><th class="r hide-sm" data-type="num"><button>Cash</button></th><th class="r hide-sm">Reports through</th><th>FEC</th></tr></thead><tbody>{orow}</tbody></table></div>
<p class="src">Source: FEC bulk files weball26 and cn26 (statutory 2026 candidates only); published {tm(http_date_to_iso(m.fec.get('source', {}).get('weball', {}).get('last_modified', '')))}.</p>"""
    site.page("candidates/", "Independent candidates for Congress 2026: odds and money | Independents Tracker",
              f"All {len(m.candidates)} independent House and Senate candidates listed by Kalshi or Polymarket in 2026, with live odds and FEC fundraising, plus {len(others)} other independent filers.",
              body, nav="candidates/", crumbs=[("Candidates", None)], priority="0.9")


def dist_rows(outcomes, fmt_label=lambda s: s):
    return "".join(
        f'<div class="row"><span>{E(fmt_label(o["label"]))}</span><span class="track"><i style="width:{max(0, min(100, (o.get("price") or 0) * 100)):.1f}%"></i></span><span class="r num">{pct(o.get("price"))}</span></div>'
        for o in outcomes)


def home_page(site):
    m = site.m
    cfg = site.cfg
    eday = date.fromisoformat(cfg["site"]["election_date"])
    days = (eday - m.now.date()).days
    countdown = (f'<span class="countdown">Election Day, Tuesday, Nov. 3: <span data-countdown="{eday.isoformat()}">{days} days</span></span>'
                 if days >= 0 else "")
    k_count = m.agg("kalshi", "KXINDCOUNT")
    p_count = m.agg("polymarket", "how-many-independents")
    k_sen, k_house = m.agg("kalshi", "KXISENATEWON"), m.agg("kalshi", "KXIHOUSEWON")
    k_any = m.agg("kalshi", "KXUSINDEPENDENTCONGRESS")
    p_ctrl = m.agg("polymarket", "which-party-will-win-the-senate")
    fulcrum = []
    if p_count:
        fulcrum.append(f'<div class="card"><div class="venue polymarket">Polymarket</div><h3>{E(p_count["title"])}</h3><div class="dist">{dist_rows(p_count["outcomes"])}</div>'
                       f'<p class="src">Source: {a_out(p_count["url"], "Polymarket " + p_count["id"], "polymarket")}; read {tm(m.mk.get("fetched_at"))}.</p></div>')
    if k_count:
        fulcrum.append(f'<div class="card"><div class="venue kalshi">Kalshi</div><h3>{E(k_count["title"])}</h3><div class="dist">{dist_rows(k_count["outcomes"])}</div>'
                       f'<p class="src">Source: {a_out(k_count["url"], "Kalshi " + k_count["series"], "kalshi")}; read {tm(m.mk.get("fetched_at"))}.</p></div>')
    side = []
    for a in (k_sen, k_house):
        if a:
            side.append(f'<h3 class="small">{E(a["title"])}</h3><div class="dist">{dist_rows(a["outcomes"])}</div>')
    if k_any and k_any["outcomes"]:
        side.append(f'<h3 class="small">{E(k_any["title"])}</h3><div class="kpi">{pct(k_any["outcomes"][0].get("price"))} <small>yes</small></div>')
    if side:
        fulcrum.append(f'<div class="card"><div class="venue kalshi">Kalshi, by chamber</div>{"".join(side)}<p class="src">Source: Kalshi series {", ".join(E(a["series"]) for a in (k_sen, k_house, k_any) if a)}; read {tm(m.mk.get("fetched_at"))}.</p></div>')
    ctrl = ""
    if p_ctrl:
        ctrl = (f'<p class="small muted">For context, Polymarket\'s “{E(p_ctrl["title"])}”: '
                + ", ".join(f'{E(o["label"])} {pct(o.get("price"))}' for o in p_ctrl["outcomes"])
                + f'. ({a_out(p_ctrl["url"], "source", "polymarket")}, read {tm(m.mk.get("fetched_at"))})</p>')
    cards = []
    for c in m.candidates[:12]:
        k, p = c["venues"].get("kalshi"), c["venues"].get("polymarket")
        bits = []
        if k:
            ch = m.delta("kalshi", k["o"])
            bits.append(f'<span class="venue kalshi">Kalshi</span> <strong class="num">{pct(k["o"].get("price"))}</strong> <span class="small">{change_html(ch)}</span>')
        if p:
            bits.append(f'<span class="venue polymarket">Polymarket</span> <strong class="num">{pct(p["o"].get("price"))}{"*" if p["kind"] == "party" else ""}</strong>')
        if not bits:
            bits.append('<span class="small muted">No market lists this candidate</span>')
        cards.append(f"""<div class="card"><h3><a href="candidates/{c['slug']}/">{E(c['display'])}</a> {chip('I', 'I-' + c['state'])}</h3>
<div class="small muted">{E(race_label(c['state'], c['office'], c['district']))}{' · ' + E(site.cfg['slate'].get('label', '')) if c['slate'] else ''}</div>
<p style="margin:8px 0 4px">{'<br>'.join(bits)}</p>
<div class="small">Raised <strong>{money(c['receipts'])}</strong> · cash {money(c['coh'])} <span class="tiny">(FEC, through {E(fmt_date(c['cvg_end']))})</span></div></div>""")
    # Party-line teaser
    teaser = []
    for chamber in ("Senate", "House"):
        spells = [(s, mm) for mm in m.members if mm["chamber"] == chamber and mm["current"] and not mm.get("delegate")
                  for s in [mm["spells"][-1]] if s.get("score") is not None and s["pu_cast"] >= 50]
        spells.sort(key=lambda x: x[0]["score"])
        rows = "".join(f'<tr><td><a href="party-line/{mm["slug"]}/">{E(mm["name"])}</a> {chip(s["party"], s["party"] + "-" + mm["state"])}</td><td class="r num">{pct(s["score"])}</td></tr>'
                       for s, mm in spells[:6])
        teaser.append(f'<div class="card"><h3>{chamber}: least party-line</h3><div class="table-wrap"><table><thead><tr><th>Member</th><th class="r">Votes with party</th></tr></thead><tbody>{rows}</tbody></table></div></div>')
    vv_last = max((c.get("last_date", "") for c in m.votes.get("chambers", {}).values()), default="")
    n_ind = len(m.candidates)
    raised = sum(c["receipts"] for c in m.candidates)
    title = "Independents Tracker: can independents win in 2026? Live odds, money, party-line votes"
    desc = (f"Live Kalshi and Polymarket odds and FEC money for the {n_ind} independent candidates for Congress in markets for 2026, "
            "plus how often every member of Congress votes with their party. Every number sourced and dated.")
    jsonld = [{"@context": "https://schema.org", "@type": "WebSite", "name": "Independents Tracker", "url": site.abs(""),
               "description": desc}]
    body = f"""<h1>Can independents win in 2026?</h1>
<p class="lede">Live prediction-market odds and campaign money for every independent candidate for Congress that Kalshi or Polymarket lists, and a party-line score for every member of Congress. Neutral, sourced, updated hourly.</p>
{countdown}
<h2>Will independents hold the balance of power?</h2>
<div class="grid three">{''.join(fulcrum)}</div>
{ctrl}
<h2>The independents, by market odds</h2>
<p class="small muted">{n_ind} independent candidates appear in 2026 House or Senate markets. Together they report {money(raised)} raised. * Polymarket's market asks whether any independent wins that race.</p>
<div class="grid three">{''.join(cards)}</div>
<p><a class="btn" href="candidates/">All candidates and independent filers →</a></p>
<h2>Who votes against their own party?</h2>
<p class="small muted">Share of party-line votes on which each member sided with their party's majority, 119th Congress, through {E(fmt_date(vv_last))}. Lowest first; current voting members with at least 50 such votes.</p>
<div class="grid two">{''.join(teaser)}</div>
<p><a class="btn" href="party-line/">Every member's party-line score →</a></p>
<h2>How this works</h2>
<p>Prices come from the public read APIs of <a href="https://kalshi.com" rel="noopener">Kalshi</a> and <a href="https://polymarket.com" rel="noopener">Polymarket</a>, money from the FEC's nightly bulk files, and votes from <a href="https://voteview.com" rel="noopener">Voteview</a>. A scheduled job rereads them every hour and rebuilds this site; nothing is typed in by hand. <a href="methodology/">Methodology</a> · <a href="data/">Data</a></p>"""
    site.page("", title, desc, body, jsonld=jsonld, priority="1.0")


def score_phrase(mem, s):
    if s.get("score") is None:
        return "No party-line votes yet"
    own = PARTY_WORD.get(s["own"], "")
    return f"Votes with the {own} majority on {pct(s['score'])} of party-line votes"


def member_page(site, mem):
    m = site.m
    path = f"party-line/{mem['slug']}/"
    s = mem["spells"][-1]
    chamber = mem["chamber"]
    role = ("Delegate" if mem.get("delegate") else "U.S. Representative") if chamber == "House" else "U.S. Senator"
    where = STATES.get(mem["state"], mem["state"])
    if chamber == "House" and not mem.get("delegate") and mem["district"] not in ("", "0", "00"):
        where += f"'s {ordinal(int(mem['district']))} district"
    elif chamber == "House" and not mem.get("delegate"):
        where += " (at large)"
    party_now = mem["party_now"]
    caucus_txt = f", caucuses with {mem['caucus']}s" if s["party"] == "I" and mem.get("caucus") else ""
    vv_last = m.votes.get("chambers", {}).get(chamber, {}).get("last_date", "")
    head_score = pct(s["score"]) if s.get("score") is not None else "n/a"
    own_word = PARTY_WORD.get(s["own"], "")
    title = f"{mem['name']}: votes with the {own_word} majority {head_score} of the time (119th Congress) | Independents Tracker"
    desc = (f"How often {mem['name']} ({s['party']}-{mem['state']}) votes with the {own_word} majority: {head_score} of {s['pu_cast']} party-line votes "
            f"in the 119th Congress through {fmt_date(vv_last)}, breaking {s['breaks_total']} times. Every vote linked to the official record.")
    spell_rows = []
    for sp in mem["spells"]:
        rank = ""
        if sp.get("rank_low"):
            rank = f"{ordinal(sp['rank_low'])}-lowest of {sp['rank_of']} {chamber} {PARTY_NOUN.get(sp['party'], '')}"
        spell_rows.append(f"""<tr><td>{chip(sp['party'], PARTY_WORD.get(sp['party'], 'Other').capitalize() if sp['party'] != 'I' else 'Independent')}</td>
<td class="nowrap">{E(fmt_date(sp['first']))} – {E(fmt_date(sp['last']))}</td>
<td class="r num">{pct(sp['score']) if sp.get('score') is not None else 'n/a'}</td><td class="r num">{sp['with_own']} of {sp['pu_cast']}</td>
<td class="r num hide-sm">{pct(sp['with_d'] / sp['pu_cast']) if sp['pu_cast'] else 'n/a'}</td><td class="r num hide-sm">{pct(sp['with_r'] / sp['pu_cast']) if sp['pu_cast'] else 'n/a'}</td>
<td class="hide-sm">{E(rank)}</td></tr>""")
    missed_total = sum(sp["missed"] for sp in mem["spells"])
    roll_total = sum(sp["rollcalls"] for sp in mem["spells"])
    summary = []
    if s.get("score") is not None:
        summary.append(f"{E(mem['name'])} ({s['party']}-{E(mem['state'])}){E(caucus_txt)} voted with the {E(own_word)} majority on "
                       f"<strong>{pct(s['score'])}</strong> of the {s['pu_cast']} party-line votes {'cast as an independent' if s['party'] == 'I' else 'cast'} "
                       f"in the 119th Congress through {E(fmt_date(s['last']))}, and against it {s['breaks_total']} times.")
    if s.get("rank_low"):
        summary.append(f"Among {s['rank_of']} {chamber} {PARTY_NOUN.get(s['party'], '')} with at least 50 such votes, that is the "
                       f"<strong>{ordinal(s['rank_low'])}-lowest</strong> score.")
    if len(mem["spells"]) > 1:
        prev = mem["spells"][-2]
        summary.append(f"Before that, as {'an' if prev['party'] == 'I' else 'a'} {E(PARTY_MEMBER.get(prev['party'], 'member'))} ({E(fmt_date(prev['first']))} – {E(fmt_date(prev['last']))}), "
                       f"the score was {pct(prev['score'])}.")
    summary.append(f"Missed {missed_total} of {roll_total} roll calls ({pct(missed_total / roll_total) if roll_total else 'n/a'}).")
    # Breaks table
    brows = []
    for key in s["breaks"][:40]:
        r = m.rc.get(key)
        if not r:
            continue
        own = s["own"]
        party_vote = r["maj"].get(own)
        mv = "Nay" if party_vote == "Y" else "Yea"
        pv = "Yea" if party_vote == "Y" else "Nay"
        bill = a_out(r["bill_url"], r["bill_label"], "congress") if r.get("bill_label") else ""
        desc_txt = r["desc"] or r["question"]
        brows.append(f"""<tr><td>{E(fmt_date(r['date']))}</td><td>{bill}<div>{E(desc_txt)}</div><div class="tiny">{E(r['question'])} · {E(r['result'])}</div></td>
<td><span class="vote">{mv}</span><div class="tiny">{E(PARTY_NOUN.get(own, ''))}: {pv}</div></td>
<td class="hide-sm">{a_out(r['url'], 'Official record', 'clerk')}<br>{a_out(r['vv'], 'Voteview', 'voteview')}</td></tr>""")
    breaks_html = ""
    if brows:
        breaks_html = f"""<h2>Votes against the {E(own_word)} majority</h2>
<p class="small muted">The {min(40, s['breaks_total'])} most recent of {s['breaks_total']} party-line votes on which {E(mem['name'])} voted against the {E(own_word)} majority{' (as an independent)' if s['party'] == 'I' else ''}.</p>
<div class="table-wrap"><table class="breaks"><thead><tr><th>Date</th><th>Measure</th><th>Vote</th><th class="hide-sm">Record</th></tr></thead><tbody>{''.join(brows)}</tbody></table></div>"""
    cand_html = ""
    for fid in mem.get("fec_ids", []):
        cc = next((c for c in m.candidates if c["id"] == fid), None)
        if cc:
            label = "as an independent" if cc["party"] == "IND" else f"without a major-party label (FEC: {cc['party_label']})"
            cand_html = (f'<div class="callout">{E(mem["name"])} is a 2026 candidate {E(label)}. '
                         f'<a href="../../candidates/{cc["slug"]}/">Odds and money for the race</a>.</div>')
    page_url = site.abs(path)
    badge_url = site.abs(f"badge/m/{mem['slug']}.svg")
    share_text = f"{mem['name']} ({s['party']}-{mem['state']}) votes with the {own_word} majority {head_score} of the time on party-line votes (119th Congress)."
    jsonld = [{"@context": "https://schema.org", "@type": "ProfilePage", "name": title, "url": page_url,
               "dateModified": m.votes.get("fetched_at") or iso(m.now), "description": desc,
               "mainEntity": {"@type": "Person", "name": mem["name"], "jobTitle": role,
                              "memberOf": {"@type": "GovernmentOrganization", "name": "United States " + ("House of Representatives" if chamber == "House" else "Senate")}}}]
    if s.get("rank_low"):
        rank_note = f"Among {chamber} {PARTY_NOUN.get(s['party'], 'members')} with 50+ party-line votes"
    elif s["party"] == "I":
        rank_note = "Independents are not ranked against a party"
    elif mem.get("delegate"):
        rank_note = "Delegates vote only in the Committee of the Whole"
    else:
        rank_note = "Fewer than 50 party-line votes so far"
    links = " · ".join(x for x in [a_out(mem["voteview"], "Voteview profile", "voteview"),
                                    a_out(mem["congress_gov"], "Congress.gov", "congress") if mem.get("congress_gov") else ""] if x)
    body = f"""<h1>{E(mem['name'])}</h1>
<p class="lede">{E(role)}, {E(where)} · {E(party_now)}{E(caucus_txt)}{'' if mem.get('current') else ' · former member'}</p>
{cand_html}
<div class="grid three">
<div class="card"><div class="small muted">{E(score_phrase(mem, s))}</div><div class="kpi">{head_score}</div><div class="tiny">{s['with_own']} of {s['pu_cast']} party-line votes{', as an independent' if s['party'] == 'I' else ''}</div></div>
<div class="card"><div class="small muted">Votes against that majority</div><div class="kpi">{s['breaks_total']}</div><div class="tiny">119th Congress, through {E(fmt_date(s['last']))}</div></div>
<div class="card"><div class="small muted">Rank within party</div><div class="kpi">{ordinal(s['rank_low']) + '<small> lowest of ' + str(s['rank_of']) + '</small>' if s.get('rank_low') else '<small>not ranked</small>'}</div><div class="tiny">{rank_note}</div></div>
</div>
<p>{' '.join(summary)}</p>
<p class="src">Source: Voteview roll-call data for the 119th Congress (through {E(fmt_date(vv_last))}), files updated {tm(http_date_to_iso(m.votes.get('source', {}).get(chamber[0] + '_votes', {}).get('last_modified', '')))}. A party-line vote is one where most voting Democrats opposed most voting Republicans. {links}</p>
<h2>By party</h2>
<div class="table-wrap"><table><thead><tr><th>As</th><th>Period</th><th class="r">Party-line score</th><th class="r">Votes with own party</th><th class="r hide-sm">With Democrats</th><th class="r hide-sm">With Republicans</th><th class="hide-sm">Rank</th></tr></thead>
<tbody>{''.join(spell_rows)}</tbody></table></div>
{breaks_html}
{embed_block(site, page_url, badge_url, f"{mem['name']} party-line score, Independents Tracker", 'm-' + mem['slug'])}
<h2>Share</h2>
{share_block(page_url, share_text)}
<p class="small muted"><a href="../">Compare every member</a> · <a href="../../methodology/#party-line">How the score works</a> · <a href="https://github.com/{E(site.cfg['site']['repo'])}/issues/new?title={E('Correction: ' + mem['name'])}" rel="noopener">Report a correction</a></p>"""
    site.page(path, title, desc, body, nav="party-line/", og="og/party-line.png", jsonld=jsonld,
              crumbs=[("Party-line index", "party-line/"), (mem["name"], None)],
              priority="0.7" if mem.get("current") else "0.4")
    site.write(f"badge/m/{mem['slug']}.svg", graphics.badge(f"{mem['name']} votes with party", f"{head_score} · 119th Congress",
                                                            f"{mem['name']}: {head_score} party-line score, through {fmt_date(s['last'])}"))


def party_line_page(site):
    m = site.m
    sections = []
    for chamber in ("House", "Senate"):
        rows = []
        mems = [mm for mm in m.members if mm["chamber"] == chamber]
        def order(x):
            sp = x["spells"][-1]
            return (bool(x.get("delegate")), sp["pu_cast"] < 50, sp["score"] if sp["score"] is not None else 2, x["name"])
        for mm in sorted(mems, key=order):
            s = mm["spells"][-1]
            dist = mm["state"] + ("" if chamber == "Senate" else "-" + ("AL" if mm["district"] in ("0", "00", "") else mm["district"].zfill(2)))
            note = "" if mm.get("current") else ' <span class="tiny">(former)</span>'
            if mm.get("delegate"):
                note += ' <span class="tiny">(delegate)</span>'
            if len(mm["spells"]) > 1:
                note += ' <span class="tiny">(changed party)</span>'
            sc = s["score"]
            rows.append(f"""<tr data-party="{s['party']}"><td><a href="{mm['slug']}/">{E(mm['name'])}</a>{note}</td><td>{E(dist)}</td><td>{chip(s['party'])}</td>
<td class="r num" data-v="{'' if sc is None else sc}">{pct(sc) if sc is not None else 'n/a'}<div class="bar"><i style="width:{(sc or 0) * 100:.1f}%"></i></div></td>
<td class="r num" data-v="{s['pu_cast']}">{s['pu_cast']}</td><td class="r num" data-v="{s['breaks_total']}">{s['breaks_total']}</td></tr>""")
        tid = f"pl-{chamber.lower()}"
        ch = m.votes.get("chambers", {}).get(chamber, {})
        sections.append(f"""<h2 id="{chamber.lower()}">{chamber}</h2>
<p class="small muted">{ch.get('party_unity_votes', 0)} party-line votes out of {ch.get('rollcalls', 0)} roll calls, {E(fmt_date(ch.get('first_date', '')))} – {E(fmt_date(ch.get('last_date', '')))}.</p>
<div class="filters"><input type="search" placeholder="Filter by name or state" data-filter="#{tid}" aria-label="Filter {chamber}">
<select data-filter="#{tid}" data-key="party" aria-label="Party"><option value="">All parties</option><option value="D">Democrats</option><option value="R">Republicans</option><option value="I">Independents</option></select>
<span class="small muted"><span data-count="#{tid}">{len(rows)}</span> shown</span></div>
<div class="table-wrap"><table id="{tid}" data-sort><thead><tr><th><button>Member</button></th><th><button>State</button></th><th><button>Party</button></th>
<th class="r" data-type="num"><button>Votes with party</button></th><th class="r" data-type="num"><button>Party-line votes</button></th><th class="r" data-type="num"><button>Breaks</button></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>""")
    vv_last = max((c.get("last_date", "") for c in m.votes.get("chambers", {}).values()), default="")
    body = f"""<h1>Party-line voting in the 119th Congress</h1>
<p class="lede">How often each member of the House and Senate votes with their party's majority when the two parties split. Lowest scores first: the members most likely to cross their party. Members with fewer than 50 such votes, and delegates, are listed last.</p>
<p>A <strong>party-line vote</strong> is a roll call on which most voting Democrats opposed most voting Republicans. A member's score is the share of those votes on which the member sided with their own party's majority. Independents are scored against the party they caucus with. A member who switched parties is listed under their current party, with the earlier record on their page. <a href="../methodology/#party-line">Full method</a>.</p>
{''.join(sections)}
<p class="src">Source: Voteview roll-call data, 119th Congress, through {E(fmt_date(vv_last))}; names and caucus from the congress-legislators project. Recomputed whenever Voteview publishes new votes.</p>"""
    site.page("party-line/", "Party-line voting scores for every member of Congress (119th) | Independents Tracker",
              "How often every House member and senator votes with their party's majority on party-line votes in the 119th Congress, with every vote against the party linked to the official record.",
              body, nav="party-line/", og="og/party-line.png", crumbs=[("Party-line index", None)], priority="0.9")


def methodology_page(site):
    cfg = site.cfg
    codes = ", ".join(f"{k} ({v})" for k, v in cfg["fec"]["independent_codes"].items())
    body = f"""<h1>Methodology</h1>
<p class="lede">Where every number comes from, how it is computed, and what it does not mean.</p>
<h2 id="candidates">Which candidates are tracked</h2>
<p>A candidate gets a page when both are true: (1) the FEC lists them as a 2026 statutory candidate for the U.S. House or Senate under one of these party labels: {E(codes)}; and (2) a Kalshi or Polymarket market for that race names them, or names a generic “independent” outcome and they are the only independent in the race who has reported more than $100,000. A market listing is the best automatic signal that a candidate is actually on the general-election ballot; FEC registration alone is not. The seven candidates of the {E(cfg['slate']['name'])} also get pages whether or not a market lists them. Independent filers with no market are listed in a table, not given pages.</p>
<p>Governor and other state races are not covered yet: their campaign money is filed with each state, not the FEC, and prediction markets keep candidates who have withdrawn (Michigan's market still lists a candidate who left the race in May 2026), so they need checks this tracker cannot yet run automatically.</p>
<h2 id="odds">Prediction-market odds</h2>
<ul>
<li><strong>Sources:</strong> the public read APIs of Kalshi (<code>api.elections.kalshi.com/trade-api/v2</code>) and Polymarket (<code>gamma-api.polymarket.com</code>, price history from <code>clob.polymarket.com</code>). No account or key is used.</li>
<li><strong>Implied chance:</strong> the midpoint between the best bid and best ask when they are at most {cfg['markets']['max_spread_for_midpoint'] * 100:.0f}¢ apart, otherwise the last trade. This is Polymarket's own display rule, applied to both venues. A price of 26¢ on a contract that pays $1 if the candidate wins is read as a 26% implied chance.</li>
<li><strong>What it is not:</strong> a poll or a forecast. Prices reflect what traders are willing to pay, including fees, risk and their own biases. Markets with little volume can move on a single trade, so pages flag any market with under ${cfg['markets']['thin_market_volume_usd']:,} traded.</li>
<li><strong>Different questions:</strong> Kalshi and Polymarket sometimes ask different questions about the same race (“Will Dan Osborn win?” against “Will an independent win?”). Each card quotes its market's exact question.</li>
<li><strong>Freshness:</strong> prices are read every hour; each card shows the time of the read. The 24-hour change compares against the stored reading closest to 24 hours earlier. History before this tracker started comes from each platform's own daily price history.</li>
</ul>
<h2 id="money">Campaign money</h2>
<p>From the FEC's nightly bulk files (<code>weball26</code>, candidate summaries; <code>cn26</code>, candidate master), which need no key. Raised is total receipts for the 2025–26 two-year period; “from the candidate” adds the candidate's own contributions and loans; cash on hand is at the end of the latest report, whose date is shown. Outside spending (super PACs, party committees) is not included. Mailing addresses in the FEC files are never published here.</p>
<h2 id="party-line">Party-line score</h2>
<ul>
<li><strong>Source:</strong> <a href="https://voteview.com/data" rel="noopener">Voteview</a> roll-call files for the 119th Congress (Lewis, Poole, Rosenthal, Boche, Rudkin and Sonnet), with names, caucus and FEC ids from the public-domain <a href="https://github.com/unitedstates/congress-legislators" rel="noopener">congress-legislators</a> project.</li>
<li><strong>Party-line vote</strong> (Congressional Quarterly's “party unity” vote): a roll call on which a majority of voting Democrats opposed a majority of voting Republicans. Yea and nay only; “present” and not voting are left out.</li>
<li><strong>Score:</strong> the share of party-line votes a member cast on which they voted with their own party's majority. Independents are scored against the party they caucus with (from congress-legislators), and their votes with each party are shown too.</li>
<li><strong>Party switchers:</strong> Voteview gives a member a new record when they change party, and so does this tracker: each period is scored on its own.</li>
<li><strong>Rank:</strong> within the member's chamber and party, among members with at least 50 party-line votes. Delegates, who vote only in the Committee of the Whole, are not ranked.</li>
<li><strong>Every break is linked</strong> to the Clerk of the House or Senate record and to Voteview, so any line can be checked.</li>
<li><strong>Limits:</strong> all roll calls count equally, procedural votes included, and a low score is not a judgment: it can reflect a district, a principle or a protest from either side.</li>
</ul>
<h2 id="polls">Why there is no polling average yet</h2>
<p>There is no open, licensed feed of 2026 race polls since FiveThirtyEight's poll database closed in 2025. Copying averages from other sites would break their terms, so this tracker shows markets and money and leaves polls out until a reusable source exists.</p>
<h2 id="schedule">Update schedule</h2>
<p>A GitHub Actions job runs every hour: it rereads the markets, checks whether the FEC or Voteview files changed (and downloads them if so), runs the test suite, rebuilds every page and publishes the site. If a source fails, its last good data stays up with its original as-of time. The code and every data snapshot are public in the <a href="https://github.com/{E(cfg['site']['repo'])}" rel="noopener">repository</a>.</p>
<h2 id="neutral">Neutrality</h2>
<p>No endorsements, no rankings of candidates by merit, no donation links for candidates. Candidates are ordered by market price, members by score. Corrections are welcome as <a href="https://github.com/{E(cfg['site']['repo'])}/issues" rel="noopener">GitHub issues</a>.</p>"""
    site.page("methodology/", "Methodology: odds, money and party-line scores | Independents Tracker",
              "How the Independents Tracker reads Kalshi and Polymarket prices, FEC campaign money and Voteview roll calls, and how the party-line score is computed.",
              body, nav="methodology/", crumbs=[("Methodology", None)], priority="0.5")


def about_page(site):
    cfg = site.cfg
    body = f"""<h1>About</h1>
<p class="lede">An automated, neutral tracker of whether independent candidates can win seats in Congress, and of how often sitting members vote with their party.</p>
<h2>What it is</h2>
<p>Pages are generated from public data by a scheduled job and published on GitHub Pages. No one edits the numbers by hand. The code, the data snapshots and the full history of every change are public.</p>
<h2>What it is not</h2>
<ul><li>Not affiliated with any candidate, campaign, party, PAC (including Independents Win PAC), the Independent National Convention, Kalshi or Polymarket.</li>
<li>Not an endorsement of anyone, and not a solicitation to donate, trade or vote.</li>
<li>Not financial advice. Prediction-market prices are shown as public information.</li></ul>
<h2>Corrections</h2>
<p>Open an issue in the <a href="https://github.com/{E(cfg['site']['repo'])}/issues" rel="noopener">repository</a> with the page and the source that shows the error. Data errors at the source (FEC, Voteview, the markets) are fixed when the source fixes them.</p>
<h2>Privacy</h2>
<p>No cookies, no accounts, no tracking pixels. If site analytics are switched on, they are cookieless (GoatCounter) and count page views and a few button clicks only.</p>
<h2>Licenses and credits</h2>
<p>Code: MIT. Derived FEC and roll-call data: public domain (CC0), with credit requested to the FEC, Voteview and the congress-legislators project. Market prices are the platforms' data, shown with attribution and links; please use their APIs and terms for any reuse.</p>"""
    site.page("about/", "About the Independents Tracker", "A neutral, automated tracker of independent candidates for Congress and party-line voting. Not affiliated with any campaign, party, PAC or market.",
              body, nav="about/", crumbs=[("About", None)], priority="0.3")


def data_page(site):
    m = site.m
    # Downloadable files: derived from public-domain sources only.
    cand_rows = [["fec_id", "name", "fec_party_label", "office", "state", "district", "slate", "kalshi_contract", "kalshi_implied",
                  "polymarket_market", "polymarket_implied", "polymarket_question_kind", "receipts", "individual_contributions",
                  "from_candidate", "disbursements", "cash_on_hand", "debts", "reports_through", "page"]]
    for c in m.candidates:
        k, p = c["venues"].get("kalshi"), c["venues"].get("polymarket")
        cand_rows.append([c["id"], c["display"], c["party_label"], c["office"], c["state"], c["district"], "yes" if c["slate"] else "no",
                          k["o"]["id"] if k else "", k["o"].get("price") if k else "", p["o"]["id"] if p else "",
                          p["o"].get("price") if p else "", p["kind"] if p else "", c["receipts"], c["indiv"], c["self"],
                          c["disb"], c["coh"], c["debts"], c["cvg_end"], site.abs(f"candidates/{c['slug']}/")])
    member_rows = [["bioguide", "name", "chamber", "state", "district", "party", "own_party_for_score", "first_vote", "last_vote",
                    "party_line_votes_cast", "with_own_party", "score", "with_democrats", "with_republicans", "breaks",
                    "rank_lowest_in_party", "party_size_ranked", "rollcalls", "missed", "page"]]
    for mm in m.members:
        for s in mm["spells"]:
            member_rows.append([mm["bioguide"], mm["name"], mm["chamber"], mm["state"], mm["district"], s["party"], s["own"] or "",
                                s["first"], s["last"], s["pu_cast"], s["with_own"], "" if s["score"] is None else s["score"],
                                s["with_d"], s["with_r"], s["breaks_total"], s.get("rank_low", ""), s.get("rank_of", ""),
                                s["rollcalls"], s["missed"], site.abs(f"party-line/{mm['slug']}/")])
    for name, rows in (("data/candidates.csv", cand_rows), ("data/party-line-119.csv", member_rows)):
        full = os.path.join(site.out, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", newline="", encoding="utf-8") as f:
            csv.writer(f, lineterminator="\n").writerows(rows)
    jsonld = [{
        "@context": "https://schema.org", "@type": "Dataset",
        "name": "Party-line (party unity) scores, 119th U.S. Congress",
        "description": "For every member of the House and Senate in the 119th Congress: party-line votes cast, votes with own party's majority, score, votes against the party, by party period. Computed from Voteview roll calls.",
        "url": site.abs("data/"), "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "creator": {"@type": "Organization", "name": "Independents Tracker"},
        "isBasedOn": ["https://voteview.com/data", "https://github.com/unitedstates/congress-legislators"],
        "temporalCoverage": "2025-01-03/..", "dateModified": m.votes.get("fetched_at", iso(m.now)),
        "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": site.abs("data/party-line-119.csv")}],
    }, {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": "Independent candidates for Congress 2026: FEC money and market listings",
        "description": "Independent and no-party candidates for the U.S. House and Senate in 2026 who appear in Kalshi or Polymarket markets, with FEC campaign finance totals.",
        "url": site.abs("data/"), "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "creator": {"@type": "Organization", "name": "Independents Tracker"},
        "isBasedOn": ["https://www.fec.gov/data/browse-data/?tab=bulk-data"],
        "dateModified": m.mk.get("fetched_at", iso(m.now)),
        "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": site.abs("data/candidates.csv")}],
    }]
    body = f"""<h1>Data</h1>
<p class="lede">Download what this site shows. Rebuilt every hour from the sources below.</p>
<div class="grid two">
<div class="card"><h3><a href="party-line-119.csv">party-line-119.csv</a></h3><p class="small">{len(member_rows) - 1} rows: every member and party period in the 119th Congress, with party-line votes, score, breaks and rank. Public domain (CC0).</p></div>
<div class="card"><h3><a href="candidates.csv">candidates.csv</a></h3><p class="small">{len(cand_rows) - 1} tracked independent candidates with FEC totals and the market contracts that list them. FEC data is public domain; implied prices are the platforms' data, shown with attribution.</p></div>
</div>
<h2>Raw snapshots</h2>
<p>Every hourly snapshot is committed to the <a href="https://github.com/{E(site.cfg['site']['repo'])}/tree/main/data" rel="noopener">repository</a> (<code>data/fec.json</code>, <code>data/markets.json</code>, <code>data/history.csv</code>, <code>data/votes.json</code>, <code>data/rollcalls.json</code>), so any number on this site can be traced to the moment it was read.</p>
<h2>Sources</h2>
<ul><li>FEC bulk data: <a href="https://www.fec.gov/data/browse-data/?tab=bulk-data" rel="noopener">fec.gov/data/browse-data</a></li>
<li>Voteview: <a href="https://voteview.com/data" rel="noopener">voteview.com/data</a></li>
<li>congress-legislators: <a href="https://github.com/unitedstates/congress-legislators" rel="noopener">github.com/unitedstates/congress-legislators</a></li>
<li>Kalshi public API: <a href="https://docs.kalshi.com" rel="noopener">docs.kalshi.com</a></li>
<li>Polymarket public API: <a href="https://docs.polymarket.com" rel="noopener">docs.polymarket.com</a></li></ul>"""
    site.page("data/", "Download: independent candidates and party-line scores | Independents Tracker",
              "CSV downloads of party-line scores for every member of the 119th Congress and of 2026 independent candidates with FEC money. Public domain.",
              body, nav="data/", jsonld=jsonld, crumbs=[("Data", None)], priority="0.5")


def not_found(site):
    from urllib.parse import urlparse
    base = urlparse(site.url).path.rstrip("/") + "/"
    body = f"""<h1>Page not found</h1><p>That page does not exist, or a candidate left the tracked list.</p>
<p><a class="btn" href="{E(base)}">Go to the tracker</a> <a class="btn" href="{E(base)}candidates/">All candidates</a> <a class="btn" href="{E(base)}party-line/">Party-line index</a></p>"""
    site.page("404.html", "Not found | Independents Tracker", "Page not found.", body, index=False)


def feed(site):
    """Atom feed: one entry per day with each tracked independent's closing price on each venue."""
    m = site.m
    days = sorted({r["ts"][:10] for r in m.hist}, reverse=True)[:14]
    entries = []
    for d in days:
        lines = []
        for c in m.candidates:
            bits = []
            for src in ("kalshi", "polymarket"):
                v = c["venues"].get(src)
                if not v:
                    continue
                pts = [r for r in m.hist if r["source"] == src and r["market"] == v["o"]["id"] and r["ts"][:10] == d]
                if pts:
                    bits.append(f"{VENUE[src]} {pct(float(sorted(pts, key=lambda r: r['ts'])[-1]['price']))}")
            if bits:
                lines.append(f"{c['display']} ({race_label(c['state'], c['office'], c['district'], short=True)}): {', '.join(bits)}")
        if not lines:
            continue
        content = "\n".join(lines)
        entries.append(f"""<entry><title>Independent candidates' odds, {E(fmt_date(d))}</title>
<id>tag:theguysaccount.github.io,2026:independents-win-tracker:{d}</id><updated>{d}T23:59:59Z</updated>
<link href="{E(site.abs('candidates/'))}"/><content type="text">{E(content)}</content></entry>""")
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Independents Tracker: daily odds</title>
<id>{E(site.abs(''))}</id><link href="{E(site.abs(''))}"/><link rel="self" href="{E(site.abs('feed.xml'))}"/>
<updated>{iso(m.now)}</updated><author><name>Independents Tracker</name></author>
{''.join(entries)}
</feed>
"""
    site.write("feed.xml", xml)


def seo_files(site, indexnow_key):
    urls = "".join(f"<url><loc>{E(site.abs(p))}</loc><lastmod>{lm}</lastmod><priority>{pr}</priority></url>\n" for p, lm, pr in site.pages)
    site.write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
    site.write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {site.abs('sitemap.xml')}\n")
    if indexnow_key:
        site.write(f"{indexnow_key}.txt", indexnow_key)
    site.write("urls.txt", "\n".join(site.abs(p) for p, _, _ in site.pages) + "\n")
    site.write(".nojekyll", "")


# ---------------------------------------------------------------- entry point

def build(out=None, site_url=None, env=None, now=None, data_dir=DATA):
    env = dict(os.environ if env is None else env)
    cfg = load_config()
    out = out or os.path.join(ROOT, "_site")
    site_url = site_url or env.get("SITE_URL") or cfg["site"]["default_url"]
    now = now or now_utc()
    model = Model(cfg, read_json(os.path.join(data_dir, "fec.json"), {}), read_json(os.path.join(data_dir, "markets.json"), {}),
                  read_json(os.path.join(data_dir, "votes.json"), {}), read_json(os.path.join(data_dir, "rollcalls.json"), {}),
                  read_json(os.path.join(data_dir, "status.json"), {}), read_history(os.path.join(data_dir, "history.csv")), now)
    # Keep pre-rendered share images across rebuilds of the same output folder.
    keep_og = os.path.join(out, "og")
    saved = {}
    if os.path.isdir(keep_og):
        for fn in os.listdir(keep_og):
            with open(os.path.join(keep_og, fn), "rb") as f:
                saved[fn] = f.read()
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    shutil.copytree(os.path.join(ROOT, "static"), os.path.join(out, "static"))
    os.makedirs(os.path.join(out, "og"), exist_ok=True)
    for fn, blob in saved.items():
        with open(os.path.join(out, "og", fn), "wb") as f:
            f.write(blob)
    if not os.path.exists(os.path.join(out, "og", "home.png")):
        shutil.copy(os.path.join(ROOT, "static", "og-default.png"), os.path.join(out, "og", "home.png"))
    if not os.path.exists(os.path.join(out, "og", "party-line.png")):
        shutil.copy(os.path.join(ROOT, "static", "og-default.png"), os.path.join(out, "og", "party-line.png"))
    site = Site(out, site_url, cfg, model, env)
    home_page(site)
    candidates_page(site)
    for c in model.candidates:
        candidate_page(site, c)
    party_line_page(site)
    for mem in model.members:
        member_page(site, mem)
    methodology_page(site)
    about_page(site)
    data_page(site)
    not_found(site)
    feed(site)
    key_path = os.path.join(ROOT, "config", "indexnow-key.txt")
    key = ""
    if os.path.exists(key_path):
        with open(key_path) as f:
            key = f.read().strip()
    seo_files(site, key)
    return site


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--site-url", default=None)
    a = ap.parse_args(argv)
    site = build(out=a.out, site_url=a.site_url)
    print(f"built {len(site.pages)} pages into {site.out}")


if __name__ == "__main__":
    main()
