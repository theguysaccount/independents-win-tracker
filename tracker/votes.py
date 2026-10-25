"""Voteview roll calls -> data/votes.json (one record per member) and data/rollcalls.json.

Sources (no key):
  Voteview  https://voteview.com/static/data/out/{members,rollcalls,votes}/{H,S}119_*.csv
            Lewis, Poole, Rosenthal, Boche, Rudkin and Sonnet, "Voteview: Congressional Roll-Call
            Votes Database", https://voteview.com/
  congress-legislators (public domain) for display names, caucus and FEC ids of current members.

Party-line (party unity) score, the standard Congressional Quarterly definition:
  A party-unity vote is a roll call on which a majority of voting Democrats opposed a majority of
  voting Republicans. A member's score is the share of the party-unity votes they cast (yea or nay)
  on which they voted with their own party's majority. Independents are scored against the party
  they caucus with, and their votes with each party are shown as well.
A member who changes party gets a separate record for each party (Voteview gives each a new id).
"""
import csv
import io
import os
import re
from collections import Counter, defaultdict

from .common import DATA, http_get, iso, now_utc, person_name, read_json, slugify, write_json

CONGRESS = 119
VV = "https://voteview.com/static/data/out/{kind}/{ch}{congress}_{kind}.csv"
LEGISLATORS = "https://unitedstates.github.io/congress-legislators/legislators-current.json"
OUT = os.path.join(DATA, "votes.json")
OUT_RC = os.path.join(DATA, "rollcalls.json")

YEA, NAY = {"1", "2", "3"}, {"4", "5", "6"}
PARTY = {"100": "D", "200": "R", "328": "I"}
PARTY_NAME = {"D": "Democrat", "R": "Republican", "I": "Independent"}
CAUCUS = {"Democrat": "D", "Republican": "R"}
MIN_PU_FOR_RANK = 50
MAX_BREAKS = 60


def sources(congress=CONGRESS):
    out = {}
    for ch in "HS":
        for kind in ("members", "rollcalls", "votes"):
            out[f"{ch}_{kind}"] = VV.format(kind=kind, ch=ch, congress=congress)
    out["legislators"] = LEGISLATORS
    return out


def remote_versions(congress=CONGRESS):
    out = {}
    for key, url in sources(congress).items():
        _, h = http_get(url, method="HEAD", timeout=30)
        out[key] = {"url": url, "last_modified": h.get("last-modified", ""), "etag": h.get("etag", "")}
    return out


def download(congress=CONGRESS):
    return {key: http_get(url, timeout=180)[0].decode("utf-8") for key, url in sources(congress).items()}


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def official_url(chamber, date, session, clerk_roll, congress=CONGRESS):
    if not clerk_roll:
        return ""
    if chamber == "House":
        return f"https://clerk.house.gov/Votes/{date[:4]}{int(clerk_roll)}"
    return (f"https://www.senate.gov/legislative/LIS/roll_call_votes/vote{congress}{session}/"
            f"vote_{congress}_{session}_{int(clerk_roll):05d}.htm")


_BILL_TYPES = [("HCONRES", "house-concurrent-resolution"), ("HJRES", "house-joint-resolution"),
               ("HRES", "house-resolution"), ("HR", "house-bill"),
               ("SCONRES", "senate-concurrent-resolution"), ("SJRES", "senate-joint-resolution"),
               ("SRES", "senate-resolution"), ("S", "senate-bill")]


def bill_url(bill, congress=CONGRESS):
    b = (bill or "").upper().replace(" ", "").replace(".", "")
    m = re.fullmatch(r"PN(\d+)(?:-\d+)?", b)
    if m:
        return f"https://www.congress.gov/nomination/{congress}th-congress/{m.group(1)}"
    for prefix, path in _BILL_TYPES:
        m = re.fullmatch(prefix + r"(\d+)", b)
        if m:
            return f"https://www.congress.gov/bill/{congress}th-congress/{path}/{m.group(1)}"
    return ""


def bill_label(bill):
    b = (bill or "").upper().replace(" ", "")
    for prefix, label in [("HCONRES", "H.Con.Res."), ("HJRES", "H.J.Res."), ("HRES", "H.Res."), ("HR", "H.R."),
                          ("SCONRES", "S.Con.Res."), ("SJRES", "S.J.Res."), ("SRES", "S.Res."), ("PN", "PN"), ("S", "S.")]:
        if re.fullmatch(prefix + r"\d+(?:-\d+)?", b):
            return label + " " + b[len(prefix):]
    return bill or ""


def legislator_index(legislators):
    """bioguide -> display name, official name, caucus, FEC ids, district, current party."""
    idx = {}
    for x in legislators:
        n = x.get("name", {})
        first = n.get("nickname") or n.get("first", "")
        display = " ".join(p for p in [first, n.get("last", "")] if p)
        if n.get("suffix"):
            display += " " + n["suffix"]
        t = (x.get("terms") or [{}])[-1]
        idx[x["id"]["bioguide"]] = {
            "name": display, "official": n.get("official_full") or display,
            "party": t.get("party", ""), "caucus": t.get("caucus") or "",
            "fec": x["id"].get("fec", []), "type": t.get("type", ""), "district": t.get("district"),
            "state": t.get("state", ""), "url": t.get("url", ""),
        }
    return idx


def build(texts, congress=CONGRESS, versions=None):
    import json
    legis = legislator_index(json.loads(texts["legislators"])) if texts.get("legislators") else {}
    members, rollcalls, chambers = [], {}, {}
    used_slugs = set()
    for ch, chamber in (("H", "House"), ("S", "Senate")):
        mrows = [m for m in _rows(texts[f"{ch}_members"]) if m["chamber"] == chamber]
        rrows = _rows(texts[f"{ch}_rollcalls"])
        party_of = {m["icpsr"]: PARTY.get(m["party_code"], "O") for m in mrows}
        votes = defaultdict(dict)  # rollnumber -> icpsr -> 'Y' | 'N' | '9'
        for v in _rows(texts[f"{ch}_votes"]):
            c = v["cast_code"]
            votes[v["rollnumber"]][v["icpsr"]] = "Y" if c in YEA else "N" if c in NAY else "P" if c in ("7", "8") else "9"
        rc_info, pu_rolls = {}, []
        for r in rrows:
            rn = r["rollnumber"]
            tally = Counter()
            for icpsr, vote in votes.get(rn, {}).items():
                if vote in ("Y", "N"):
                    tally[(party_of.get(icpsr, "O"), vote)] += 1
            maj = {}
            for p in ("D", "R"):
                y, n = tally[(p, "Y")], tally[(p, "N")]
                maj[p] = "Y" if y > n else "N" if n > y else None
            is_pu = maj["D"] is not None and maj["R"] is not None and maj["D"] != maj["R"]
            rc_info[rn] = {"maj": maj, "pu": is_pu, "tally": tally, "row": r}
            if is_pu:
                pu_rolls.append(rn)
        dates = sorted(r["date"] for r in rrows)
        chambers[chamber] = {"rollcalls": len(rrows), "party_unity_votes": len(pu_rolls),
                             "first_date": dates[0] if dates else "", "last_date": dates[-1] if dates else ""}

        # One record per member (bioguide), with one spell per Voteview id (party).
        by_bio = defaultdict(list)
        for m in mrows:
            by_bio[m["bioguide_id"] or m["icpsr"]].append(m)
        for bio, spells_rows in by_bio.items():
            L = legis.get(bio, {})
            caucus = CAUCUS.get(L.get("caucus", ""), None)
            spells = []
            for m in spells_rows:
                icpsr, p = m["icpsr"], party_of[m["icpsr"]]
                cast = missed = present = 0
                pu_cast = with_own = with_d = with_r = 0
                first = last = ""
                breaks = []
                own = p if p in ("D", "R") else caucus
                rows_for = [(rn, rc_info[rn]) for rn in sorted(rc_info, key=int) if icpsr in votes.get(rn, {})]
                for rn, info in rows_for:
                    vote = votes[rn][icpsr]
                    d = info["row"]["date"]
                    first = first or d
                    last = d
                    if vote in ("Y", "N"):
                        cast += 1
                    elif vote == "P":
                        present += 1
                    else:
                        missed += 1
                    if info["pu"] and vote in ("Y", "N"):
                        pu_cast += 1
                        with_d += vote == info["maj"]["D"]
                        with_r += vote == info["maj"]["R"]
                        if own and vote == info["maj"][own]:
                            with_own += 1
                        elif own:
                            breaks.append(rn)
                if not rows_for:
                    continue
                if own is None and pu_cast:  # an independent with no recorded caucus: the party they side with most
                    own = "D" if with_d >= with_r else "R"
                    with_own = max(with_d, with_r)
                    breaks = [rn for rn, info in rows_for if info["pu"] and votes[rn][icpsr] in ("Y", "N")
                              and votes[rn][icpsr] != info["maj"][own]]
                spells.append({
                    "icpsr": int(icpsr), "party": p, "own": own, "first": first, "last": last,
                    "rollcalls": len(rows_for), "cast": cast, "missed": missed, "present": present,
                    "pu_cast": pu_cast, "with_own": with_own, "with_d": with_d, "with_r": with_r,
                    "score": round(with_own / pu_cast, 4) if pu_cast else None,
                    "breaks": [f"{ch}-{rn}" for rn in reversed(breaks)][:MAX_BREAKS],
                    "breaks_total": len(breaks),
                    "nominate": float(m["nominate_dim1"]) if m.get("nominate_dim1") not in ("", None) else None,
                })
                for rn in breaks[-MAX_BREAKS:]:
                    rollcalls.setdefault(f"{ch}-{rn}", rc_info[rn])
            if not spells:
                continue
            spells.sort(key=lambda s: s["last"])
            m0 = spells_rows[-1]
            name = L.get("name") or person_name(m0["bioname"])
            dist = m0["district_code"] if chamber == "House" else ""
            slug = slugify(f"{name} {m0['state_abbrev']}")
            if slug in used_slugs:
                slug = slugify(f"{name} {m0['state_abbrev']} {chamber}")
            used_slugs.add(slug)
            members.append({
                "bioguide": bio, "slug": slug, "name": name, "official": L.get("official") or person_name(m0["bioname"]),
                "chamber": chamber, "state": m0["state_abbrev"], "district": dist,
                "delegate": chamber == "House" and m0["state_abbrev"] in ("DC", "PR", "GU", "VI", "AS", "MP"),
                "current": bio in legis and (L.get("type") == ("rep" if chamber == "House" else "sen")),
                "caucus": L.get("caucus", ""), "party_now": PARTY_NAME.get(spells[-1]["party"], "Other"),
                "fec_ids": L.get("fec", []), "spells": spells,
                "voteview": f"https://voteview.com/person/{spells[-1]['icpsr']}",
                "congress_gov": f"https://www.congress.gov/member/{slugify(name)}/{bio}" if bio[:1].isalpha() else "",
            })

    # Ranks: within each chamber and party, among spells with enough party-unity votes to be stable.
    groups = defaultdict(list)
    for m in members:
        for s in m["spells"]:
            if s["score"] is not None and s["pu_cast"] >= MIN_PU_FOR_RANK and s["party"] in ("D", "R"):
                groups[(m["chamber"], s["party"])].append(s)
    for key, spells in groups.items():
        spells.sort(key=lambda s: (s["score"], -s["pu_cast"]))
        for i, s in enumerate(spells, 1):
            s["rank_low"] = i       # 1 = votes against its party most often
            s["rank_of"] = len(spells)

    rc_out = {}
    for key, info in rollcalls.items():
        r = info["row"]
        chamber = r["chamber"]
        t = info["tally"]
        rc_out[key] = {
            "chamber": chamber, "date": r["date"], "rollnumber": int(r["rollnumber"]),
            "clerk": r.get("clerk_rollnumber", ""), "session": r.get("session", ""),
            "bill": r.get("bill_number", ""), "bill_label": bill_label(r.get("bill_number", "")),
            "desc": (r.get("vote_desc") or r.get("dtl_desc") or "").strip(),
            "question": (r.get("vote_question") or "").strip(), "result": (r.get("vote_result") or "").strip(),
            "yea": int(r.get("yea_count") or 0), "nay": int(r.get("nay_count") or 0),
            "maj": info["maj"], "d": [t[("D", "Y")], t[("D", "N")]], "r": [t[("R", "Y")], t[("R", "N")]],
            "url": official_url(chamber, r["date"], r.get("session", ""), r.get("clerk_rollnumber", ""), congress),
            "vv": f"https://voteview.com/rollcall/R{chamber[0]}{congress}{int(r['rollnumber']):04d}",
            "bill_url": bill_url(r.get("bill_number", ""), congress),
        }
    members.sort(key=lambda m: (m["chamber"], m["state"], m["name"]))
    return {"congress": congress, "source": versions or {}, "chambers": chambers, "members": members}, rc_out


def refresh(cfg, force=False):
    prev = read_json(OUT, {})
    versions = remote_versions()
    unchanged = prev and all(prev.get("source", {}).get(k, {}).get("last_modified") == v["last_modified"]
                             for k, v in versions.items())
    if unchanged and not force:
        return {"changed": False, "note": "Voteview files unchanged"}
    texts = download()
    out, rc = build(texts, versions=versions)
    out["fetched_at"] = iso(now_utc())
    n = len(out["members"])
    if n < 400:
        raise RuntimeError(f"Voteview parse produced {n} members; keeping the previous data")
    write_json(OUT, out, compact=True)
    write_json(OUT_RC, rc, compact=True)
    return {"changed": True, "note": f"{n} members, {sum(c['party_unity_votes'] for c in out['chambers'].values())} party-unity votes"}
