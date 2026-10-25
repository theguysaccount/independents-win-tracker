"""Weekly self-test of the live site. Exit 1 if anything a visitor would notice is broken or stale.

  python3 -m tracker.selftest --site-url https://theguysaccount.github.io/independents-win-tracker

Checks every URL in the live sitemap answers 200, the key pages carry their sources, the market
read time on the live home page is recent, and the share images, badges and key file resolve.
"""
import argparse
import concurrent.futures
import os
import re
import sys
from datetime import timedelta

from .common import ROOT, http_get, load_config, now_utc, parse_iso

MAX_MARKET_AGE = timedelta(hours=6)


def fetch(url):
    try:
        body, h = http_get(url, timeout=30, retries=2)
        return 200, body
    except Exception as e:  # HTTPError has .code; anything else counts as down
        return getattr(e, "code", 0), b""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-url", default=load_config()["site"]["default_url"])
    a = ap.parse_args(argv)
    base = a.site_url.rstrip("/")
    problems = []

    code, home = fetch(base + "/")
    if code != 200:
        print(f"FAIL home page answered {code}")
        return 1
    html = home.decode("utf-8", "replace")
    m = re.search(r'Markets \(Kalshi, Polymarket\): <time datetime="([^"]+)"', html)
    read_at = parse_iso(m.group(1)) if m else None
    if not read_at:
        problems.append("home page shows no market read time")
    elif now_utc() - read_at > MAX_MARKET_AGE:
        problems.append(f"market prices on the live site are stale: read {m.group(1)}")

    code, sm = fetch(base + "/sitemap.xml")
    urls = re.findall(r"<loc>([^<]+)</loc>", sm.decode("utf-8", "replace")) if code == 200 else []
    if len(urls) < 400:
        problems.append(f"sitemap lists {len(urls)} URLs (expected 400+), status {code}")
    extra = [base + "/robots.txt", base + "/feed.xml", base + "/og/home.png", base + "/data/party-line-119.csv",
             base + "/data/candidates.csv", base + "/static/style.css"]
    with open(os.path.join(ROOT, "config", "indexnow-key.txt")) as f:
        key = f.read().strip()
    extra.append(f"{base}/{key}.txt")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda u: (u, fetch(u)), urls + extra))
    for u, (c, body) in results:
        if c != 200:
            problems.append(f"{u} answered {c}")
        elif "/candidates/" in u and u.rstrip("/").count("/") > base.count("/") + 1:
            t = body.decode("utf-8", "replace")
            if "fec.gov/data/candidate/" not in t or "<time" not in t:
                problems.append(f"{u} lacks its sources")
    for p in problems[:40]:
        print("FAIL", p)
    print(f"selftest: {len(urls)} sitemap URLs and {len(extra)} assets checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
