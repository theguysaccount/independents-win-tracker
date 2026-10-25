"""Kalshi + Polymarket public prices -> data/markets.json and data/history.csv.

Both platforms publish read-only market data without a key:
  Kalshi      https://api.elections.kalshi.com/trade-api/v2 (events, markets, candlesticks)
  Polymarket  https://gamma-api.polymarket.com (events, markets) and https://clob.polymarket.com (price history)

Discovery (daily, or when no tracked set exists) scans every open Kalshi event and the Polymarket
race events for 2026 House and Senate races, and keeps each outcome that names a candidate the FEC
lists without a major-party label. Every other run re-reads only the tracked events, so an hourly
refresh costs about 30 requests.

The displayed "implied chance" follows Polymarket's own display rule for both venues: the midpoint
of the best bid and best ask when the spread is at most 10 cents, otherwise the last trade.
"""
import csv
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from .common import (DATA, STATE_BY_NAME, STATES, fold, get_json, given, iso, now_utc, parse_iso,
                     race_key, read_json, slugify, surname, write_json)

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
OUT = os.path.join(DATA, "markets.json")
HISTORY = os.path.join(DATA, "history.csv")


# ---------------------------------------------------------------- prices

def _f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


def implied(bid, ask, last, max_spread=0.10):
    """Midpoint when the book is tight enough to mean something, else the last trade."""
    if bid is not None and ask is not None and 0 < ask and bid <= ask and ask - bid <= max_spread + 1e-9:
        return round((bid + ask) / 2, 4)
    return last


def kalshi_quote(m, max_spread=0.10):
    bid, ask, last = _f(m.get("yes_bid_dollars")), _f(m.get("yes_ask_dollars")), _f(m.get("last_price_dollars"))
    # Older API responses quoted whole cents.
    if bid is None and m.get("yes_bid") is not None:
        bid = m["yes_bid"] / 100
    if ask is None and m.get("yes_ask") is not None:
        ask = m["yes_ask"] / 100
    if last is None and m.get("last_price") is not None:
        last = m["last_price"] / 100
    if ask == 0:  # an empty ask side is reported as 0
        ask = None
    return {
        "bid": bid, "ask": ask, "last": last,
        "price": implied(bid, ask, last, max_spread),
        "volume": _f(m.get("volume_fp")) if m.get("volume_fp") is not None else _f(m.get("volume")),
        "volume_24h": _f(m.get("volume_24h_fp")) if m.get("volume_24h_fp") is not None else _f(m.get("volume_24h")),
        "open_interest": _f(m.get("open_interest_fp")) if m.get("open_interest_fp") is not None else _f(m.get("open_interest")),
        "prev_price": _f(m.get("previous_price_dollars")),
    }


def poly_quote(m, max_spread=0.10):
    bid, ask, last = _f(m.get("bestBid")), _f(m.get("bestAsk")), _f(m.get("lastTradePrice"))
    price = None
    try:
        prices = m.get("outcomePrices")
        prices = __import__("json").loads(prices) if isinstance(prices, str) else prices
        price = _f(prices[0]) if prices else None
    except (ValueError, TypeError, IndexError):
        price = None
    if price is None:
        price = implied(bid, ask, last, max_spread)
    return {
        "bid": bid, "ask": ask, "last": last, "price": price,
        "volume": _f(m.get("volumeNum")) if m.get("volumeNum") is not None else _f(m.get("volume")),
        "volume_24h": _f(m.get("volume24hr")),
        "liquidity": _f(m.get("liquidityNum")) if m.get("liquidityNum") is not None else _f(m.get("liquidity")),
        "day_change": _f(m.get("oneDayPriceChange")),
    }


# ---------------------------------------------------------------- races and names

_K_SENATE = [re.compile(r"^(?P<state>[A-Z][A-Za-z .]+?) Senate (?:winner|race)\b"),
             re.compile(r"^Who will win the Senate race in (?P<state>[A-Z][A-Za-z .]+?)\?")]
_K_HOUSE_D = re.compile(r"\b(?P<st>[A-Z]{2})-(?P<d>\d{1,2}|AL)\b")
_K_HOUSE_AL = re.compile(r"^(?P<state>[A-Z][A-Za-z .]+?) House (?:winner|race)\b")


def kalshi_race(title):
    """Race key for a Kalshi event title such as 'Nebraska Senate winner?' or 'CA-06 House winner?'."""
    t = (title or "").strip()
    if re.search(r"\b(nominee|primary|margin|turnout|vote percent|special|runoff|combo)\b", t, re.I):
        return None
    if "House" in t:
        m = _K_HOUSE_D.search(t)
        if m and m.group("st") in STATES:
            d = "00" if m.group("d") == "AL" else m.group("d").zfill(2)
            return race_key(m.group("st"), "H", d)
        m = _K_HOUSE_AL.match(t)
        if m and m.group("state").lower() in STATE_BY_NAME:
            return race_key(STATE_BY_NAME[m.group("state").lower()], "H", "00")
        return None
    if "Senate" in t:
        for rx in _K_SENATE:
            m = rx.match(t)
            if m and m.group("state").strip().lower() in STATE_BY_NAME:
                return race_key(STATE_BY_NAME[m.group("state").strip().lower()], "S")
    return None


def poly_slugs(race):
    """Polymarket's slug conventions for 2026 race-winner events."""
    st, office = race.split("-")[0], race.split("-")[1]
    if office == "S":
        return [f"{slugify(STATES[st])}-senate-election-winner"]
    d = race.split("-")[2]
    d = "al" if d == "00" else d
    return [f"{st.lower()}-{d}-house-election-winner"]


def match_candidate(label, race, fec):
    """FEC id of the candidate in `race` whose name matches a market outcome label, if exactly one."""
    sn, gn = surname(label), given(label)
    if not sn:
        return None
    hits = []
    for cid in fec.get("races", {}).get(race, []):
        c = fec["candidates"][cid]
        if surname(c["name_raw"]) != sn:
            continue
        g2 = given(c["name_raw"])
        if gn and g2 and not (gn == g2 or gn[0] == g2[0] or gn.startswith(g2) or g2.startswith(gn)):
            continue
        hits.append(cid)
    return hits[0] if len(hits) == 1 else None


_PARTY_OUTCOME = re.compile(r"^(an? )?(independent|other|third[- ]party)( candidate| party)?$", re.I)


def outcome_name(label):
    """'Todd Achilles (I)' -> 'Todd Achilles'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", (label or "").strip())


# ---------------------------------------------------------------- Kalshi

def kalshi_events_all(status="open", pause=0.25):
    events, cursor = [], ""
    for _ in range(200):
        url = f"{KALSHI}/events?status={status}&with_nested_markets=true&limit=200" + (f"&cursor={cursor}" if cursor else "")
        j = get_json(url, timeout=90)
        events += j.get("events", [])
        cursor = j.get("cursor") or ""
        if not cursor:
            break
        time.sleep(pause)
    return events


def kalshi_event(ticker):
    j = get_json(f"{KALSHI}/events/{urllib.parse.quote(ticker)}?with_nested_markets=true", timeout=60)
    ev = j.get("event", {})
    if "markets" not in ev:
        ev["markets"] = j.get("markets", [])
    return ev


def kalshi_series_open_events(series):
    j = get_json(f"{KALSHI}/events?series_ticker={urllib.parse.quote(series)}&status=open&with_nested_markets=true&limit=20", timeout=60)
    return j.get("events", [])


def kalshi_url(series_ticker):
    return f"https://kalshi.com/markets/{series_ticker.lower()}"


def kalshi_race_record(ev, race, fec, max_spread):
    outcomes = []
    for m in ev.get("markets", []):
        status = m.get("status") or ""
        result = (m.get("result") or "").lower()
        if status not in ("active", "open", "") and not result:
            continue  # paused or delisted without a result
        name = m.get("yes_sub_title") or m.get("subtitle") or ""
        cid = match_candidate(name, race, fec)
        q = kalshi_quote(m, max_spread)
        if result in ("yes", "no"):
            q["price"] = 1.0 if result == "yes" else 0.0
        outcomes.append({
            "id": m["ticker"], "label": name, "cand_id": cid,
            "question": (m.get("title") or "").replace(")s win", ") win"),
            "rules": m.get("rules_primary", ""), "status": status, "result": result, **q,
        })
    outcomes.sort(key=lambda o: -(o["price"] or 0))
    return {
        "source": "kalshi", "id": ev["event_ticker"], "race": race,
        "title": ev.get("title", ""), "series": ev.get("series_ticker", ""),
        "url": kalshi_url(ev.get("series_ticker", "")), "outcomes": outcomes,
    }


def _volume(rec):
    return sum(o.get("volume") or 0 for o in rec["outcomes"])


def best_per_race(records):
    """One event per venue and race: some races have several Kalshi series (party and person markets)."""
    best = {}
    for r in records:
        k = (r["source"], r["race"])
        if k not in best or _volume(r) > _volume(best[k]):
            best[k] = r
    return sorted(best.values(), key=lambda r: (r["race"], r["source"]))


def kalshi_discover(fec, max_spread):
    """Every open 2026 Kalshi House/Senate event that lists an independent candidate."""
    found = []
    for ev in kalshi_events_all():
        if not ev.get("event_ticker", "").endswith("-26"):
            continue
        race = kalshi_race(ev.get("title"))
        if not race or race not in fec.get("races", {}):
            continue
        rec = kalshi_race_record(ev, race, fec, max_spread)
        if any(o["cand_id"] and fec["candidates"][o["cand_id"]]["independent"] for o in rec["outcomes"]):
            found.append(rec)
    return best_per_race(found)


# ---------------------------------------------------------------- Polymarket

def poly_event(slug):
    j = get_json(f"{GAMMA}/events?slug={urllib.parse.quote(slug)}", timeout=60)
    return j[0] if isinstance(j, list) and j else None


def poly_race_record(ev, race, fec, max_spread):
    ind_ids = [cid for cid in fec.get("races", {}).get(race, []) if fec["candidates"][cid]["independent"]]
    outcomes = []
    for m in ev.get("markets", []):
        if m.get("outcomePrices") in (None, "", "[]"):
            continue  # placeholder rows ("Person B") that were never opened
        if not m.get("active") and not m.get("closed"):
            continue
        label = (m.get("groupItemTitle") or m.get("question") or "").strip()
        name = outcome_name(label)
        cid, party_outcome = match_candidate(name, race, fec), False
        if not cid and _PARTY_OUTCOME.match(name):
            party_outcome = True
        q = poly_quote(m, max_spread)
        result = ""
        if m.get("closed") and q["price"] in (0.0, 1.0):
            result = "yes" if q["price"] == 1.0 else "no"
        outcomes.append({
            "id": str(m["id"]), "label": label, "cand_id": cid, "party_outcome": party_outcome,
            "question": m.get("question", ""), "token": _first_token(m),
            "status": "closed" if m.get("closed") else "active", "result": result, **q,
        })
    outcomes.sort(key=lambda o: -(o["price"] or 0))
    # A generic "Independent" outcome speaks for the race's independent only if there is exactly one
    # independent in this race with real money; it is still labeled with its own question on the page.
    serious = [cid for cid in ind_ids if fec["candidates"][cid]["receipts"] >= 100000]
    for o in outcomes:
        if o["party_outcome"] and len(serious) == 1:
            o["covers"] = serious[0]
    return {
        "source": "polymarket", "id": ev.get("slug"), "race": race, "title": (ev.get("title") or "").strip(),
        "url": f"https://polymarket.com/event/{ev.get('slug')}", "outcomes": outcomes,
    }


def _first_token(m):
    try:
        toks = m.get("clobTokenIds")
        toks = __import__("json").loads(toks) if isinstance(toks, str) else toks
        return toks[0] if toks else ""
    except (ValueError, TypeError):
        return ""


def poly_discover(fec, races, max_spread):
    found = []
    for race in sorted(races):
        for slug in poly_slugs(race):
            try:
                ev = poly_event(slug)
            except Exception:
                ev = None
            if not ev:
                continue
            rec = poly_race_record(ev, race, fec, max_spread)
            if any((o["cand_id"] and fec["candidates"][o["cand_id"]]["independent"]) or o.get("covers")
                   for o in rec["outcomes"]):
                found.append(rec)
            time.sleep(0.2)
    return found


# ---------------------------------------------------------------- aggregates

def aggregates(cfg, max_spread):
    out = []
    for series in cfg["markets"].get("kalshi_aggregate_series", []):
        try:
            evs = kalshi_series_open_events(series)
        except Exception:
            continue
        for ev in evs[:1]:
            outs = []
            for m in ev.get("markets", []):
                q = kalshi_quote(m, max_spread)
                outs.append({"id": m["ticker"], "label": m.get("yes_sub_title") or "Yes", "question": m.get("title", ""), **q})
            out.append({"source": "kalshi", "id": ev["event_ticker"], "title": ev.get("title", ""),
                        "series": series, "url": kalshi_url(series), "outcomes": outs})
    for slug in cfg["markets"].get("polymarket_aggregate_slugs", []):
        try:
            ev = poly_event(slug)
        except Exception:
            ev = None
        if not ev:
            continue
        outs = []
        for m in ev.get("markets", []):
            if not m.get("active") or m.get("closed") or m.get("outcomePrices") in (None, "", "[]"):
                continue
            outs.append({"id": str(m["id"]), "label": (m.get("groupItemTitle") or "").strip(),
                         "question": m.get("question", ""), "token": _first_token(m), **poly_quote(m, max_spread)})
        out.append({"source": "polymarket", "id": slug, "title": (ev.get("title") or "").strip(),
                    "url": f"https://polymarket.com/event/{slug}", "outcomes": outs})
    return out


# ---------------------------------------------------------------- history

HIST_COLS = ["ts", "source", "market", "price"]


def read_history(path=HISTORY):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f)]


def write_history(rows, path=HISTORY):
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HIST_COLS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in HIST_COLS})
    os.replace(tmp, path)


def compact_history(rows, now, keep_hourly_days=14):
    """Hourly points for the last two weeks, one point per day (the last) before that."""
    cutoff = now - timedelta(days=keep_hourly_days)
    seen, out = {}, []
    for r in sorted(rows, key=lambda r: (r["source"], r["market"], r["ts"])):
        ts = parse_iso(r["ts"])
        if ts is None:
            continue
        if ts >= cutoff:
            key = (r["source"], r["market"], r["ts"][:13])
        else:
            key = (r["source"], r["market"], r["ts"][:10])
        seen[key] = r
    out = sorted(seen.values(), key=lambda r: (r["ts"], r["source"], r["market"]))
    return out


def backfill(source, outcome, series=None, days=365):
    """Daily closes from the platform's own history endpoint, for a newly tracked market."""
    pts = []
    end = int(time.time())
    try:
        if source == "kalshi" and series:
            j = get_json(f"{KALSHI}/series/{series}/markets/{outcome['id']}/candlesticks?start_ts={end - days * 86400}&end_ts={end}&period_interval=1440", timeout=60)
            for c in j.get("candlesticks", []):
                p = _f((c.get("price") or {}).get("close_dollars"))
                if p is None:
                    b, a = _f((c.get("yes_bid") or {}).get("close_dollars")), _f((c.get("yes_ask") or {}).get("close_dollars"))
                    p = implied(b, a, None)
                if p is not None:
                    pts.append((datetime.fromtimestamp(c["end_period_ts"], timezone.utc), p))
        elif source == "polymarket" and outcome.get("token"):
            j = get_json(f"{CLOB}/prices-history?market={outcome['token']}&interval=max&fidelity=1440", timeout=60)
            for h in j.get("history", []):
                pts.append((datetime.fromtimestamp(h["t"], timezone.utc), float(h["p"])))
    except Exception:
        return []
    return [{"ts": iso(t.replace(minute=0, second=0)), "source": source, "market": outcome["id"], "price": f"{p:.4f}"}
            for t, p in pts]


# ---------------------------------------------------------------- refresh

def _linked(o):
    return bool(o.get("cand_id") or o.get("covers"))


def refresh(cfg, fec, discover=False, now=None):
    """Re-read tracked markets (or rediscover them) and append this hour's prices to the history.

    A failed request for one event keeps that event's previous record (marked stale) instead of
    dropping it; only a run where every request fails raises, which leaves data/markets.json as it was.
    """
    now = now or now_utc()
    enabled = cfg.get("sources_enabled", {})
    max_spread = cfg["markets"].get("max_spread_for_midpoint", 0.10)
    prev = read_json(OUT, {}) or {}
    prev_races = {(r["source"], r["id"]): r for r in prev.get("races", [])}
    need_discovery = discover or not prev_races
    races, notes, errors = [], [], []

    def keep_stale(key, err):
        errors.append(f"{key[0]} {key[1]}: {err}")
        if key in prev_races:
            races.append(dict(prev_races[key], stale=True))

    if enabled.get("kalshi", True):
        if need_discovery:
            try:
                k = kalshi_discover(fec, max_spread)
                notes.append(f"kalshi discovery: {len(k)} events")
                races += k
            except Exception as e:  # discovery failed: fall back to the tracked set
                errors.append(f"kalshi discovery: {e}")
                for key, r in prev_races.items():
                    if key[0] == "kalshi":
                        races.append(dict(r, stale=True))
        else:
            for key, r in prev_races.items():
                if key[0] != "kalshi":
                    continue
                try:
                    races.append(kalshi_race_record(kalshi_event(key[1]), r["race"], fec, max_spread))
                except Exception as e:
                    keep_stale(key, e)
                time.sleep(0.15)
    if enabled.get("polymarket", True):
        if need_discovery:
            ind_races = {c["race"] for c in fec["candidates"].values() if c["independent"] and c["receipts"] >= 25000}
            p = poly_discover(fec, ind_races, max_spread)
            notes.append(f"polymarket discovery: {len(p)} events")
            races += p
        else:
            for key, r in prev_races.items():
                if key[0] != "polymarket":
                    continue
                try:
                    ev = poly_event(key[1])
                    if ev:
                        races.append(poly_race_record(ev, r["race"], fec, max_spread))
                    else:
                        keep_stale(key, "event not found")
                except Exception as e:
                    keep_stale(key, e)
                time.sleep(0.15)

    try:
        agg = aggregates(cfg, max_spread)
    except Exception as e:
        errors.append(f"aggregates: {e}")
        agg = prev.get("aggregates", [])
    fresh = [r for r in races if not r.get("stale")]
    if not fresh:
        raise RuntimeError("no market could be read (" + "; ".join(errors[:3]) + "); keeping the previous data")

    # History: backfill newly tracked markets, then add this hour's point for each independent's
    # outcome and each aggregate outcome.
    hist = read_history()
    have = {(r["source"], r["market"]) for r in hist}
    stamp = iso(now.replace(minute=0, second=0))
    series_rows = [(rec, o) for rec in fresh for o in rec["outcomes"] if _linked(o)]
    series_rows += [(rec, o) for rec in agg for o in rec["outcomes"]]
    for rec, o in series_rows:
        if (rec["source"], o["id"]) not in have:
            hist += backfill(rec["source"], o, rec.get("series"))
            have.add((rec["source"], o["id"]))
        if o.get("price") is not None and not o.get("result"):
            hist.append({"ts": stamp, "source": rec["source"], "market": o["id"], "price": f"{o['price']:.4f}"})
    write_history(compact_history(hist, now))

    out = {"fetched_at": iso(now), "races": sorted(races, key=lambda r: (r["race"], r["source"])),
           "aggregates": agg, "errors": errors,
           "discovered_at": iso(now) if need_discovery else prev.get("discovered_at", iso(now))}
    write_json(OUT, out)
    n_out = sum(1 for r in races for o in r["outcomes"] if _linked(o))
    return {"changed": True, "errors": errors,
            "note": "; ".join(notes + [f"{len(races)} race markets ({len(races) - len(fresh)} stale), {n_out} independent outcomes, {len(agg)} aggregate markets"])}
