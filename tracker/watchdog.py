"""Print how many minutes old the live site's market prices are (9999 if unknown).

  python3 -m tracker.watchdog --site-url https://theguysaccount.github.io/independents-win-tracker

Used by .github/workflows/watchdog.yml to restart the update job when GitHub drops scheduled runs.
"""
import argparse
import re
import sys

from .common import http_get, load_config, now_utc, parse_iso


def age_minutes(html, now):
    m = re.search(r'Markets \(Kalshi, Polymarket\): <time datetime="([^"]+)"', html)
    t = parse_iso(m.group(1)) if m else None
    return 9999 if t is None else int((now - t).total_seconds() // 60)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-url", default=load_config()["site"]["default_url"])
    a = ap.parse_args(argv)
    try:
        body, _ = http_get(a.site_url.rstrip("/") + "/", timeout=30, retries=2)
        print(age_minutes(body.decode("utf-8", "replace"), now_utc()))
    except Exception:
        print(9999)
    return 0


if __name__ == "__main__":
    sys.exit(main())
