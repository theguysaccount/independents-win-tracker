"""Tell IndexNow search engines (Bing, Yandex, Seznam, Naver...) which pages exist or changed.

  python3 -m tracker.indexnow --urls _site/urls.txt [--prev prev-urls.txt] [--force]

Submits the whole URL list (a few hundred pages) once a day, on the 09:xx UTC run, and whenever the
set of pages changed since the live site (a new candidate, a new member). The key file
<key>.txt is published at the site root by tracker.build. A failed submission is reported but never
fails the workflow: the site is already live.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .common import ROOT, UA, now_utc


def should_submit(urls, prev, hour, force=False):
    if force:
        return True, "forced"
    if set(urls) != set(prev):
        return True, f"{len(set(urls) - set(prev))} new and {len(set(prev) - set(urls))} removed URLs"
    if hour == 9:
        return True, "daily submission"
    return False, "no new pages and not the daily slot"


def submit(urls, key, site_url):
    host = urlparse(site_url).netloc
    body = json.dumps({"host": host, "key": key, "keyLocation": f"{site_url.rstrip('/')}/{key}.txt",
                       "urlList": [u for u in urls if urlparse(u).netloc == host][:10000]}).encode()
    for attempt in range(4):
        if attempt:
            time.sleep(30 * attempt)
        req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                print(f"IndexNow: {r.status} for {len(urls)} URLs")
                return r.status
        except urllib.error.HTTPError as e:
            print(f"IndexNow: {e.code} {e.read()[:300]!r}")
            # 403 until the engine has fetched the key file for the first time; 429 and 5xx are transient.
            if e.code not in (403, 429) and e.code < 500:
                return e.code
        except Exception as e:  # network trouble: try again later
            print(f"IndexNow: {e}")
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", required=True)
    ap.add_argument("--prev", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    with open(a.urls) as f:
        urls = [u.strip() for u in f if u.strip()]
    prev = []
    if a.prev and os.path.exists(a.prev):
        with open(a.prev) as f:
            prev = [u.strip() for u in f]
    prev = [u for u in prev if u.startswith("http")]
    ok, why = should_submit(urls, prev, now_utc().hour, a.force)
    print(f"IndexNow: {'submitting' if ok else 'skipping'} ({why})")
    if ok:
        with open(os.path.join(ROOT, "config", "indexnow-key.txt")) as f:
            key = f.read().strip()
        site_url = os.environ.get("SITE_URL") or urls[0].rsplit("/", 1)[0]
        submit(urls, key, site_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
