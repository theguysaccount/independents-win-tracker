"""Check a built site before it is published. Exit 1 (and publish nothing) if anything is off.

  python3 -m tracker.guard [_site]

Checks: the key pages exist; enough candidate and member pages; every candidate page carries its
sources and read times; every internal link resolves; no advocacy language; sitemap covers the pages.
"""
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .common import ROOT

MIN_CANDIDATES = 5
MIN_MEMBERS = 400
# Advocacy the tracker must never print. Disclaimers that negate these ("not an endorsement",
# "No endorsements") are removed before the scan.
BANNED = [r"\bvote for\b", r"\bdonate (?:to|now)\b", r"\bcontribute to\b", r"\bendors(?:e|es|ed|ing|ement)\b",
          r"\bsupport (?:his|her|their) campaign\b", r"\bchip in\b", r"\bvolunteer for\b"]
ALLOWED = [r"no endorsements?", r"not an endorsement", r"not as an endorsement", r"not an endorsement of anyone",
           r"will bernie endorse", r"endorse in the"]


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.text = [], []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        for k in ("href", "src"):
            if a.get(k):
                self.links.append(a[k])

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.text.append(data)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def visible_text(html):
    p = Links()
    p.feed(html)
    return " ".join(p.text), p.links


def check(site_dir):
    errors = []
    must = ["index.html", "candidates/index.html", "party-line/index.html", "methodology/index.html", "about/index.html",
            "data/index.html", "404.html", "sitemap.xml", "robots.txt", "feed.xml", "static/style.css", "static/app.js",
            "og/home.png", "data/candidates.csv", "data/party-line-119.csv"]
    for f in must:
        if not os.path.exists(os.path.join(site_dir, f)):
            errors.append(f"missing {f}")
    cand_dir = os.path.join(site_dir, "candidates")
    cands = [d for d in os.listdir(cand_dir) if os.path.isdir(os.path.join(cand_dir, d))] if os.path.isdir(cand_dir) else []
    pl_dir = os.path.join(site_dir, "party-line")
    members = [d for d in os.listdir(pl_dir) if os.path.isdir(os.path.join(pl_dir, d))] if os.path.isdir(pl_dir) else []
    if len(cands) < MIN_CANDIDATES:
        errors.append(f"only {len(cands)} candidate pages (expected at least {MIN_CANDIDATES})")
    if len(members) < MIN_MEMBERS:
        errors.append(f"only {len(members)} member pages (expected at least {MIN_MEMBERS})")
    sitemap = _read(os.path.join(site_dir, "sitemap.xml")) if os.path.exists(os.path.join(site_dir, "sitemap.xml")) else ""
    for d in cands:
        html = _read(os.path.join(cand_dir, d, "index.html"))
        if "fec.gov/data/candidate/" not in html:
            errors.append(f"candidates/{d}: no FEC source link")
        if "Source:" not in html or "<time" not in html:
            errors.append(f"candidates/{d}: missing source line or read time")
        if f"/candidates/{d}/" not in sitemap:
            errors.append(f"candidates/{d}: not in sitemap")
        if not os.path.exists(os.path.join(site_dir, "og", f"c-{d}.png")):
            errors.append(f"candidates/{d}: share image missing")
        if not os.path.exists(os.path.join(site_dir, "badge", f"{d}.svg")):
            errors.append(f"candidates/{d}: badge missing")
    banned = [re.compile(b, re.I) for b in BANNED]
    allowed = [re.compile(a, re.I) for a in ALLOWED]
    for dirpath, _, files in os.walk(site_dir):
        for fn in files:
            if not fn.endswith(".html"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, site_dir)
            html = _read(path)
            text, links = visible_text(html)
            # Roll-call titles are quoted from the official record and may contain any words.
            if not rel.startswith("party-line/"):
                scrubbed = text
                for a in allowed:
                    scrubbed = a.sub(" ", scrubbed)
                for b in banned:
                    m = b.search(scrubbed)
                    if m:
                        errors.append(f"{rel}: advocacy phrase {m.group(0)!r}")
            if rel == "404.html":
                continue
            base = "file:///" + rel.replace(os.sep, "/")
            for link in links:
                u = urlparse(link)
                if u.scheme or link.startswith(("#", "mailto:", "data:", "//")):
                    continue
                target = urlparse(urljoin(base, u.path)).path.lstrip("/")
                full = os.path.join(site_dir, target)
                if target.endswith("/") or os.path.isdir(full):
                    full = os.path.join(full, "index.html")
                if not os.path.exists(full):
                    errors.append(f"{rel}: broken link {link}")
    return errors, {"candidates": len(cands), "members": len(members)}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    site_dir = argv[0] if argv else os.path.join(ROOT, "_site")
    errors, counts = check(site_dir)
    for e in errors[:50]:
        print("GUARD", e)
    print(f"guard: {counts['candidates']} candidate pages, {counts['members']} member pages, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
