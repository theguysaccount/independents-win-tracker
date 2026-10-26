# Independents Tracker

**Can independents win in 2026?** Live Kalshi and Polymarket odds and FEC campaign money for every
independent candidate for Congress that a prediction market lists, plus a party-line (party unity)
score for every member of the 119th Congress, with every vote against the party linked to the
official record.

**Live:** https://theguysaccount.github.io/independents-win-tracker/

- Neutral and sourced: every number shows its source and the time it was read. No endorsements.
- Fully automated: a GitHub Actions job rereads the sources twice an hour, tests, rebuilds and publishes, and a watchdog restarts it if GitHub skips a run.
- No server, no keys, no cookies. Static HTML on GitHub Pages; Python standard library only.

## What's on the site

| Page | What it answers |
|---|---|
| `/` | How many independents might win, and the independents ranked by market odds |
| `/candidates/<name>/` | One candidate: Kalshi and Polymarket prices, price history, the whole race's market, FEC money, money in the race, an embeddable badge |
| `/candidates/` | All tracked independents, plus every other independent FEC filer |
| `/party-line/` | Every member of Congress by party-line score, House and Senate |
| `/party-line/<member>/` | One member's score, rank in party, and each vote against the party |
| `/methodology/`, `/data/`, `/about/` | How it works, CSV downloads, neutrality and corrections |
| `/feed.xml`, `/sitemap.xml`, `/badge/*.svg` | Daily odds feed, sitemap, live badges |

## Run it locally

Needs Python 3.9+ and nothing else (Chrome is optional, for share images).

```bash
python3 -m tracker.refresh            # read every source that changed (FEC, Kalshi, Polymarket, Voteview)
python3 -m tracker.og --site _site    # build the site into _site/ and render share cards
python3 -m tracker.guard _site        # the checks the deploy runs
python3 -m http.server 8000 --directory _site
```

The committed `data/` folder is a complete snapshot, so `python3 -m tracker.build` works offline.

## Test

```bash
python3 -m unittest discover -s tests -v
```

Covers FEC parsing (and that addresses never leak), market discovery and name matching, the
implied-price rule, party-line scoring (including party switchers and independents' caucus),
official-record links, and a full site build from synthetic data and from the committed snapshot,
guarded for broken links, missing sources and advocacy language.

## Deploy

Pushing to `main` builds and deploys through `.github/workflows/update.yml` (GitHub Pages,
"GitHub Actions" source). The same workflow runs twice an hour. See [OPERATIONS.md](OPERATIONS.md) for
every job, how each one fails safely, and the keys a human can turn later (custom domain, money).

## Layout

```
tracker/     refresh.py (orchestrator) · fec.py · markets.py · votes.py · build.py · og.py · guard.py · indexnow.py · selftest.py
config/      tracker.json (scope, slate, thresholds) · indexnow-key.txt (public by design)
data/        committed snapshots: fec.json, markets.json, history.csv, votes.json, rollcalls.json, status.json
static/      style.css · app.js · favicon.svg · og-default.png
tests/       unit and end-to-end tests with synthetic fixtures
```

## Data and licenses

Code: MIT. Derived FEC and Voteview data: CC0; please credit the FEC, Voteview (Lewis, Poole,
Rosenthal, Boche, Rudkin and Sonnet) and the congress-legislators project. Market prices belong to
Kalshi and Polymarket and are shown with attribution; use their APIs and terms for reuse.

Not affiliated with any candidate, campaign, party, PAC, the Independent National Convention,
Kalshi or Polymarket. Corrections: open an issue.
