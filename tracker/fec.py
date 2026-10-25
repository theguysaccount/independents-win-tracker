"""FEC bulk files -> data/fec.json.

Reads two small public files the FEC rebuilds every night (no API key):
  weball26.zip  candidate summaries: receipts, spending, cash on hand, through the latest report
  cn26.zip      candidate master: election year, office, status (used to drop stale records)

Keeps every 2026 House/Senate candidate filed without a major-party label, plus every other
candidate in the same races (for the "money in this race" table). Mailing addresses in the
candidate master are never read into the output.
"""
import io
import os
import zipfile

from .common import DATA, http_get, iso, now_utc, person_name, race_key, write_json, read_json

BASE = "https://www.fec.gov/files/bulk-downloads/{cycle}/"
OUT = os.path.join(DATA, "fec.json")

# https://www.fec.gov/campaign-finance-data/all-candidates-file-description/
WEBALL = ["cand_id", "cand_name", "cand_ici", "pty_cd", "party", "ttl_receipts", "trans_from_auth",
          "ttl_disb", "trans_to_auth", "coh_bop", "coh_cop", "cand_contrib", "cand_loans", "other_loans",
          "cand_loan_repay", "other_loan_repay", "debts_owed_by", "ttl_indiv_contrib", "state", "district",
          "spec_election", "prim_election", "run_election", "gen_election", "gen_election_pct",
          "other_pol_cmte_contrib", "pol_pty_contrib", "cvg_end_dt", "indiv_refunds", "cmte_refunds"]
# https://www.fec.gov/campaign-finance-data/candidate-master-file-description/
CN = ["cand_id", "cand_name", "party", "election_yr", "state", "office", "district", "ici", "status",
      "pcc", "st1", "st2", "city", "st", "zip"]

MAJOR = {"DEM", "REP", "DFL"}  # DFL: Minnesota's Democratic-Farmer-Labor party


def _num(s):
    try:
        return round(float(s), 2) if s not in ("", None) else 0.0
    except ValueError:
        return 0.0


def _date(mmddyyyy):
    s = (mmddyyyy or "").strip()
    if len(s) == 10 and s[2] == "/":
        return f"{s[6:]}-{s[:2]}-{s[3:5]}"
    return ""


def parse_rows(text, cols):
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        f = line.split("|")
        if len(f) < len(cols):
            f += [""] * (len(cols) - len(f))
        out.append(dict(zip(cols, f)))
    return out


def _unzip_text(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = [n for n in z.namelist() if n.endswith(".txt")][0]
        return z.read(name).decode("latin-1")


def remote_versions(cycle):
    """Last-Modified of each bulk file, from a HEAD request (cheap; used to skip unchanged files)."""
    out = {}
    for key, fname in (("weball", f"weball{str(cycle)[2:]}.zip"), ("cn", f"cn{str(cycle)[2:]}.zip")):
        _, h = http_get(BASE.format(cycle=cycle) + fname, method="HEAD", timeout=30)
        out[key] = {"url": BASE.format(cycle=cycle) + fname, "last_modified": h.get("last-modified", "")}
    return out


def download(cycle):
    texts = {}
    for key, fname in (("weball", f"weball{str(cycle)[2:]}.zip"), ("cn", f"cn{str(cycle)[2:]}.zip")):
        blob, _ = http_get(BASE.format(cycle=cycle) + fname, timeout=120)
        texts[key] = _unzip_text(blob)
    return texts


def build(weball_text, cn_text, cfg, versions):
    """Pure function: bulk-file text -> the fec.json structure."""
    cycle = cfg["fec"]["cycle"]
    ind_codes = cfg["fec"]["independent_codes"]
    min_receipts = cfg["fec"].get("min_receipts_listed", 5000)
    master = {r["cand_id"]: r for r in parse_rows(cn_text, CN)}
    cands = {}
    for r in parse_rows(weball_text, WEBALL):
        cid = r["cand_id"]
        m = master.get(cid)
        office = cid[:1]
        # Only this cycle's House and Senate records for statutory candidates. The summary file
        # also carries senators elected in other years and superseded duplicate IDs.
        if office not in ("H", "S") or not m or m["election_yr"] != str(cycle) or m["status"] != "C":
            continue
        party = (r["party"] or m["party"]).strip().upper()
        dist = "00" if office == "S" else (r["district"] or m["district"] or "00").zfill(2)
        cands[cid] = {
            "id": cid,
            "name_raw": r["cand_name"],
            "name": person_name(r["cand_name"]),
            "party": party,
            "party_label": ind_codes.get(party, party),
            "independent": party in ind_codes,
            "major": party in MAJOR,
            "office": office,
            "state": r["state"] or m["state"],
            "district": dist,
            "ici": r["cand_ici"] or m["ici"],
            "pcc": m["pcc"],
            "receipts": _num(r["ttl_receipts"]),
            "indiv": _num(r["ttl_indiv_contrib"]),
            "self": round(_num(r["cand_contrib"]) + _num(r["cand_loans"]), 2),
            "other_loans": _num(r["other_loans"]),
            "pac": round(_num(r["other_pol_cmte_contrib"]) + _num(r["pol_pty_contrib"]), 2),
            "disb": _num(r["ttl_disb"]),
            "coh": _num(r["coh_cop"]),
            "debts": _num(r["debts_owed_by"]),
            "cvg_end": _date(r["cvg_end_dt"]),
        }
    for c in cands.values():
        c["race"] = race_key(c["state"], c["office"], c["district"])
    ind_races = {c["race"] for c in cands.values() if c["independent"] and c["receipts"] >= min_receipts}
    keep = {cid: c for cid, c in cands.items() if c["race"] in ind_races and (c["receipts"] > 0 or c["independent"])}
    races = {}
    for c in sorted(keep.values(), key=lambda c: -c["receipts"]):
        races.setdefault(c["race"], []).append(c["id"])
    return {
        "cycle": cycle,
        "source": versions,
        "candidates": keep,
        "races": races,
        "counts": {
            "candidates_2026": len(cands),
            "independent_filers": sum(1 for c in cands.values() if c["independent"]),
            "independent_filers_listed": sum(1 for c in keep.values() if c["independent"] and c["receipts"] >= min_receipts),
        },
    }


def refresh(cfg, force=False):
    """Download the bulk files if they changed; rewrite data/fec.json. Returns a status dict."""
    cycle = cfg["fec"]["cycle"]
    prev = read_json(OUT, {})
    versions = remote_versions(cycle)
    unchanged = prev and all(prev.get("source", {}).get(k, {}).get("last_modified") == v["last_modified"]
                             for k, v in versions.items())
    if unchanged and not force:
        return {"changed": False, "note": "FEC bulk files unchanged"}
    texts = download(cycle)
    out = build(texts["weball"], texts["cn"], cfg, versions)
    out["fetched_at"] = iso(now_utc())
    if len([c for c in out["candidates"].values() if c["independent"]]) < 10:
        raise RuntimeError("FEC parse produced fewer than 10 independent candidates; keeping the previous data")
    write_json(OUT, out)
    return {"changed": True, "note": f"{out['counts']['independent_filers_listed']} independent filers listed"}
