"""Refresh every source that changed, each one independently.

  python3 -m tracker.refresh                 # what the hourly job runs
  python3 -m tracker.refresh --discover      # also rescan the markets for newly listed independents
  python3 -m tracker.refresh --only markets  # one source
  python3 -m tracker.refresh --check-fresh   # exit 1 if a source has not been read successfully in time

A source that fails keeps its last good data file; data/status.json records the error and the last
success, and the site prints each dataset's own as-of time, so stale numbers are never shown as new.
"""
import argparse
import sys
import traceback
from datetime import timedelta

from . import fec, markets, votes
from .common import DATA, iso, load_config, now_utc, parse_iso, read_json, write_json

STATUS = DATA + "/status.json"
# How long a source may go without one successful read before --check-fresh fails the workflow.
MAX_AGE = {"fec": timedelta(days=3), "markets": timedelta(hours=6), "votes": timedelta(days=3)}
DISCOVERY_EVERY = timedelta(hours=20)


def run(only=None, discover=False, force=False, now=None):
    now = now or now_utc()
    cfg = load_config()
    status = read_json(STATUS, {}) or {}
    enabled = cfg.get("sources_enabled", {})

    def record(name, fn):
        st = status.get(name, {})
        st["checked_at"] = iso(now)
        try:
            res = fn()
            st.update(ok=True, last_success=iso(now), note=res.get("note", ""), error="",
                      warnings=res.get("errors", [])[:10])
            if res.get("changed"):
                st["last_changed"] = iso(now)
        except Exception as e:  # keep the previous data file; report and carry on with other sources
            st.update(ok=False, error=f"{type(e).__name__}: {e}"[:500])
            traceback.print_exc()
        status[name] = st
        print(f"{name}: {'ok' if st.get('ok') else 'FAILED'} {st.get('note') if st.get('ok') else st.get('error')}")

    if (not only or "fec" in only) and enabled.get("fec", True):
        record("fec", lambda: fec.refresh(cfg, force=force))
    fec_data = read_json(fec.OUT)
    if (not only or "markets" in only) and fec_data:
        last = parse_iso((read_json(markets.OUT, {}) or {}).get("discovered_at"))
        fec_changed = status.get("fec", {}).get("last_changed") == iso(now)
        disc = discover or fec_changed or last is None or now - last >= DISCOVERY_EVERY
        record("markets", lambda: markets.refresh(cfg, fec_data, discover=disc, now=now))
    if (not only or "votes" in only) and enabled.get("voteview", True):
        record("votes", lambda: votes.refresh(cfg, force=force))
    write_json(STATUS, status)
    return status


def check_fresh(now=None):
    now = now or now_utc()
    status = read_json(STATUS, {}) or {}
    bad = []
    for name, age in MAX_AGE.items():
        last = parse_iso(status.get(name, {}).get("last_success"))
        if last is None or now - last > age:
            bad.append(f"{name}: last successful read {status.get(name, {}).get('last_success', 'never')} "
                       f"(limit {age}); last error: {status.get(name, {}).get('error', '')}")
    for b in bad:
        print("STALE", b)
    return not bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated: fec,markets,votes")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-download even if the source is unchanged")
    ap.add_argument("--check-fresh", action="store_true")
    a = ap.parse_args(argv)
    if a.check_fresh:
        return 0 if check_fresh() else 1
    run(only=set(filter(None, a.only.split(","))), discover=a.discover, force=a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
