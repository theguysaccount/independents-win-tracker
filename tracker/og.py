"""Open Graph share cards (1200x630 PNG) rendered with headless Chrome.

  python3 -m tracker.og [--site _site]          # after tracker.build
  python3 -m tracker.og --default                # re-render static/og-default.png

GitHub's Ubuntu runners ship Google Chrome; locally the macOS app bundle is used. Without Chrome,
every card falls back to a copy of static/og-default.png, so pages never point at a missing image.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from html import escape as E

from .common import ROOT, money, pct, race_label

CHROMES = [os.environ.get("CHROME", ""), "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
           "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
DEFAULT = os.path.join(ROOT, "static", "og-default.png")

CSS = """
*{box-sizing:border-box}html,body{margin:0;width:1200px;height:630px;overflow:hidden}
body{background:#14121f;color:#fff;font-family:"Inter","Segoe UI","Helvetica Neue",Arial,"DejaVu Sans",sans-serif;padding:56px 64px;display:flex;flex-direction:column}
.top{display:flex;align-items:center;gap:14px;font-size:26px;font-weight:700;color:#cfc6ff}
.top i{display:inline-block;width:40px;height:40px;border-radius:9px;background:#5a3fd1}
h1{font-size:64px;line-height:1.05;letter-spacing:-1.5px;margin:34px 0 10px}
.sub{font-size:28px;color:#b8b3cc}
.row{display:flex;gap:28px;margin-top:auto}
.box{flex:1;background:#221f33;border-radius:18px;padding:22px 26px}
.box .k{font-size:20px;letter-spacing:2px;text-transform:uppercase;color:#a99cff;font-weight:700}
.box .v{font-size:58px;font-weight:800;margin-top:6px;letter-spacing:-1px}
.box .v small{font-size:22px;color:#b8b3cc;font-weight:500;letter-spacing:0}
.foot{font-size:20px;color:#8f89a6;margin-top:22px}
.list{margin-top:26px;display:flex;flex-direction:column;gap:12px}
.li{display:flex;justify-content:space-between;font-size:32px;background:#221f33;border-radius:14px;padding:14px 22px}
.li b{color:#cfc6ff}
"""


def find_chrome():
    for c in CHROMES:
        if c and (os.path.exists(c) or shutil.which(c)):
            return shutil.which(c) or c
    return None


def render(chrome, html, out_png):
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "card.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write(f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{html}</body></html>")
        cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--mute-audio",
               "--force-device-scale-factor=1", "--window-size=1200,630", f"--user-data-dir={os.path.join(d, 'profile')}",
               f"--screenshot={out_png}", "file://" + src]
        subprocess.run(cmd, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return os.path.exists(out_png) and os.path.getsize(out_png) > 1000


def card_default():
    return """<div class="top"><i></i>Independents Tracker</div>
<h1>Can independents win in 2026?</h1>
<div class="sub">Live prediction-market odds, FEC money and party-line votes for Congress. Every number sourced.</div>
<div class="row"><div class="box"><div class="k">Odds</div><div class="v">Kalshi · Polymarket</div></div>
<div class="box"><div class="k">Votes</div><div class="v">Every member</div></div></div>"""


def card_home(model, asof):
    items = []
    for c in model.candidates[:4]:
        v = c["venues"].get("kalshi") or c["venues"].get("polymarket")
        if v:
            items.append(f'<div class="li"><span>{E(c["display"])} <b>I-{E(c["state"])}</b></span><span>{pct(v["o"].get("price"))}</span></div>')
    return f"""<div class="top"><i></i>Independents Tracker</div>
<h1 style="font-size:54px;margin-top:26px">Can independents win in 2026?</h1>
<div class="list">{''.join(items)}</div>
<div class="foot">Kalshi implied chance where listed, else Polymarket · as of {E(asof)}</div>"""


def card_candidate(c, asof):
    from .build import fmt_date
    k, p = c["venues"].get("kalshi"), c["venues"].get("polymarket")
    boxes = []
    if k:
        boxes.append(f'<div class="box"><div class="k">Kalshi</div><div class="v">{pct(k["o"].get("price"))}</div></div>')
    if p:
        boxes.append(f'<div class="box"><div class="k">Polymarket{" · any independent" if p["kind"] == "party" else ""}</div><div class="v">{pct(p["o"].get("price"))}</div></div>')
    boxes.append(f'<div class="box"><div class="k">Raised (FEC)</div><div class="v">{money(c["receipts"])}</div></div>')
    return f"""<div class="top"><i></i>Independents Tracker</div>
<h1>{E(c['display'])}</h1>
<div class="sub">{E(c['party_label'])} · {E(race_label(c['state'], c['office'], c['district']))} · 2026</div>
<div class="row">{''.join(boxes)}</div>
<div class="foot">Implied chance of winning, as of {E(asof)}. Money through {E(fmt_date(c['cvg_end']))}. Not an endorsement.</div>"""


def card_party_line():
    return """<div class="top"><i></i>Independents Tracker</div>
<h1>Who votes with their party?</h1>
<div class="sub">A party-line score for every member of the 119th Congress, with every vote against the party linked to the official record.</div>
<div class="row"><div class="box"><div class="k">House</div><div class="v">435+ members</div></div><div class="box"><div class="k">Senate</div><div class="v">100 senators</div></div></div>"""


def run(site_dir, model):
    og = os.path.join(site_dir, "og")
    os.makedirs(og, exist_ok=True)
    from .build import fmt_date, fmt_dt  # noqa: F401
    asof = fmt_dt(model.mk.get("fetched_at"))
    jobs = [("home.png", card_home(model, asof)), ("party-line.png", card_party_line())]
    jobs += [(f"c-{c['slug']}.png", card_candidate(c, asof)) for c in model.candidates]
    chrome = find_chrome()
    made = 0
    for name, html in jobs:
        out = os.path.join(og, name)
        ok = False
        if chrome:
            try:
                ok = render(chrome, html, out)
            except Exception as e:
                print(f"og: {name} failed: {e}", file=sys.stderr)
        if not ok:
            shutil.copy(DEFAULT, out)
        made += ok
    print(f"og: rendered {made} of {len(jobs)} cards" + ("" if chrome else " (no Chrome: copied the default card)"))
    return made


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=os.path.join(ROOT, "_site"))
    ap.add_argument("--default", action="store_true")
    a = ap.parse_args(argv)
    if a.default:
        chrome = find_chrome()
        if not chrome:
            sys.exit("Chrome not found")
        render(chrome, card_default(), DEFAULT)
        print("wrote", DEFAULT)
        return
    from .build import build
    site = build(out=a.site)
    run(a.site, site.m)


if __name__ == "__main__":
    main()
