"""Small synthetic inputs in the exact formats of the real sources."""
import json

from tracker.fec import CN, WEBALL


def weball_line(**kw):
    row = {k: "" for k in WEBALL}
    row.update({k: str(v) for k, v in kw.items()})
    return "|".join(row[k] for k in WEBALL)


def cn_line(**kw):
    row = {k: "" for k in CN}
    row.update({k: str(v) for k, v in kw.items()})
    return "|".join(row[k] for k in CN)


CANDS = [
    # id, name, party, state, district, receipts, coh, election_yr, status, cvg
    ("S4NE00207", "OSBORN, DAN", "IND", "NE", "00", 11029845.41, 1953183.30, "2026", "C", "10/14/2026"),
    ("S6NE00129", "RICKETTS, PETE", "REP", "NE", "00", 14500000, 1200000, "2026", "C", "10/14/2026"),
    ("S6NE00145", "BURBANK, CINDY", "DE", "NE", "00", 49000, 23000, "2026", "C", "09/30/2026"),
    ("S4NE00090", "SASSE, BENJAMIN", "REP", "NE", "00", 9000, 100000, "2026", "C", "09/30/2026"),
    ("S4VT00033", "SANDERS, BERNARD", "IND", "VT", "00", 26000000, 21000000, "2030", "C", "10/14/2026"),
    ("H6AK01092", "HILL, BILL", "IND", "AK", "00", 2630792.87, 117732.32, "2026", "C", "10/14/2026"),
    ("H2AK01083", "BEGICH, NICHOLAS III", "REP", "AK", "00", 6438903.51, 1782866.69, "2026", "C", "10/14/2026"),
    ("H6ID01318", "ZABEL, SARAH", "IND", "ID", "01", 272259.88, 62333.38, "2026", "C", "10/14/2026"),
    ("H6WA09082", "SAWANT, KSHAMA", "IND", "WA", "09", 754221.76, 1864, "2026", "C", "09/30/2026"),
    ("H6TX99999", "NOBODY, NOT YET", "IND", "TX", "99", 1000, 0, "2026", "N", "09/30/2026"),
]


def fec_texts():
    w = "\n".join(weball_line(cand_id=c[0], cand_name=c[1], party=c[2], state=c[3], district=c[4], ttl_receipts=c[5],
                              ttl_indiv_contrib=c[5] * 0.9, coh_cop=c[6], ttl_disb=c[5] * 0.8, cvg_end_dt=c[9],
                              cand_ici="C", cand_contrib=10) for c in CANDS)
    n = "\n".join(cn_line(cand_id=c[0], cand_name=c[1], party=c[2], election_yr=c[7], state=c[3], office=c[0][0],
                          district=c[4], ici="C", status=c[8], st1="123 PRIVATE ST", city="SOMEWHERE", zip="00000") for c in CANDS)
    return w, n


CFG = {
    "site": {"name": "Independents Tracker", "election_date": "2026-11-03",
             "default_url": "https://example.test/independents-win-tracker", "repo": "example/independents-win-tracker"},
    "fec": {"cycle": 2026, "independent_codes": {"IND": "Independent", "NPA": "No Party Affiliation", "OTH": "Other"},
            "min_receipts_listed": 5000},
    "slate": {"label": "INC '26 slate", "name": "2026 Independent Slate", "source_name": "Example", "source_url": "https://example.test/slate",
              "fec_ids": ["S4NE00207", "H6ID01318"]},
    "exclude": {},
    "markets": {"kalshi_aggregate_series": [], "polymarket_aggregate_slugs": [], "max_spread_for_midpoint": 0.1,
                "thin_market_volume_usd": 25000},
    "sources_enabled": {"fec": True, "kalshi": True, "polymarket": True, "voteview": True},
}


def kalshi_event_ne():
    def m(ticker, name, bid, ask, last, vol):
        return {"ticker": ticker, "yes_sub_title": name, "status": "active", "yes_bid_dollars": bid, "yes_ask_dollars": ask,
                "last_price_dollars": last, "volume_fp": vol, "previous_price_dollars": "0.2400",
                "title": f"Will {name} win the Senate race in Nebraska?", "rules_primary": "If ... then Yes."}
    return {"event_ticker": "SENATENE-26", "series_ticker": "SENATENE", "title": "Nebraska Senate winner?",
            "markets": [m("SENATENE-26-R", "Pete Ricketts", "0.7500", "0.7600", "0.7500", "1842116.21"),
                        m("SENATENE-26-DOSB", "Dan Osborn", "0.2500", "0.2600", "0.2600", "1448912.33"),
                        m("SENATENE-26-D", "Cindy Burbank", "0.0010", "0.0030", "0.0010", "136290.46")]}


def kalshi_event_ak():
    def m(ticker, name, bid, ask, last):
        return {"ticker": ticker, "yes_sub_title": name, "status": "active", "yes_bid_dollars": bid, "yes_ask_dollars": ask,
                "last_price_dollars": last, "volume_fp": "10000.00", "title": f"Will {name} win?"}
    return {"event_ticker": "HOUSEAKAL-26", "series_ticker": "HOUSEAKAL", "title": "Alaska House winner?",
            "markets": [m("HOUSEAKAL-26-R", "Nick Begich III", "0.7800", "0.7900", "0.7900"),
                        m("HOUSEAKAL-26-BHIL", "Bill Hill", "0.2000", "0.2100", "0.2100")]}


def poly_event_ne():
    def m(mid, label, prices, bid, ask, last, vol, active=True):
        return {"id": mid, "groupItemTitle": label, "question": f"Will {label} win the Nebraska Senate race in 2026?",
                "outcomePrices": json.dumps(prices) if prices else None, "bestBid": bid, "bestAsk": ask, "lastTradePrice": last,
                "volumeNum": vol, "volume24hr": 1000, "liquidityNum": 5000, "active": active, "closed": False,
                "clobTokenIds": json.dumps(["111", "222"]), "oneDayPriceChange": -0.01}
    return {"slug": "nebraska-senate-election-winner", "title": "Nebraska Senate Election Winner  ",
            "markets": [m("634892", "Pete Ricketts (R)", ["0.74", "0.26"], 0.73, 0.75, 0.74, 515605),
                        m("634893", "Independent", ["0.255", "0.745"], 0.25, 0.26, 0.26, 344924),
                        m("634891", "Democrat", ["0.0005", "0.9995"], None, 0.001, 0.001, 112650),
                        m("634894", "Person B", None, 0, 1, 0, 0, active=False)]}


# Voteview: a tiny House and Senate.
H_MEMBERS = """congress,chamber,icpsr,state_icpsr,district_code,state_abbrev,party_code,occupancy,last_means,bioname,bioguide_id,born,died,nominate_dim1,nominate_dim2,nominate_log_likelihood,nominate_geo_mean_probability,nominate_number_of_votes,nominate_number_of_errors,conditional,nokken_poole_dim1,nokken_poole_dim2
119,President,99912,99,0,USA,200,0,0,"TRUMP, Donald John",,1946.0,,0.403,0.162,,,,,,,
119,House,1,1,1,AA,100,,,"ADAMS, Alice",A000001,1960.0,,-0.4,0,,,,,,,
119,House,2,1,2,AA,100,,,"BAKER, Bob",B000002,1960.0,,-0.3,0,,,,,,,
119,House,3,1,3,AA,200,,,"CRUZ, Carla",C000003,1960.0,,0.4,0,,,,,,,
119,House,4,1,4,AA,200,,,"DIAZ, Dan",D000004,1960.0,,0.5,0,,,,,,,
119,House,5,1,5,AA,200,,,"EVANS, Eve",E000005,1960.0,,0.2,0,,,,,,,
119,House,6,1,5,AA,328,,,"EVANS, Eve",E000005,1960.0,,0.1,0,,,,,,,
"""
H_ROLLCALLS = """congress,chamber,rollnumber,date,session,clerk_rollnumber,majority_requirement,yea_count,nay_count,nominate_mid_1,nominate_mid_2,nominate_spread_1,nominate_spread_2,nominate_log_likelihood,bill_number,vote_result,vote_desc,vote_question,dtl_desc
119,House,1,2025-01-10,1,5,1/2,3,2,0,0,0,0,0,HR1,Passed,A party-line bill,On Passage,
119,House,2,2025-02-10,1,6,1/2,5,0,0,0,0,0,0,HRES2,Passed,A unanimous resolution,On Agreeing to the Resolution,
119,House,3,2026-03-01,2,7,1/2,2,3,0,0,0,0,0,S3,Failed,Another split,On Passage,
119,House,4,2026-04-01,2,8,1/2,2,3,0,0,0,0,0,PN44,Failed,A nomination,On the Nomination,
"""
# r1: D yea, R nay, Eve (R) votes yea -> break. r2: all yea (not party-line).
# r3: D nay, R yea; Eve now I votes yea (with R). Baker misses. r4: D yea, R nay; Eve (I) votes yea (with D).
H_VOTES = """congress,chamber,rollnumber,icpsr,cast_code,prob
119,House,1,1,1,99
119,House,1,2,1,99
119,House,1,3,6,99
119,House,1,4,6,99
119,House,1,5,1,99
119,House,2,1,1,99
119,House,2,2,1,99
119,House,2,3,1,99
119,House,2,4,1,99
119,House,2,5,1,99
119,House,3,1,6,99
119,House,3,2,9,99
119,House,3,3,1,99
119,House,3,4,1,99
119,House,3,6,1,99
119,House,4,1,1,99
119,House,4,2,1,99
119,House,4,3,6,99
119,House,4,4,6,99
119,House,4,6,1,99
"""
S_MEMBERS = """congress,chamber,icpsr,state_icpsr,district_code,state_abbrev,party_code,occupancy,last_means,bioname,bioguide_id,born,died,nominate_dim1,nominate_dim2,nominate_log_likelihood,nominate_geo_mean_probability,nominate_number_of_votes,nominate_number_of_errors,conditional,nokken_poole_dim1,nokken_poole_dim2
119,Senate,11,1,0,BB,100,,,"FOX, Fay",F000011,1950.0,,-0.4,0,,,,,,,
119,Senate,12,1,0,BB,200,,,"GRAY, Gus",G000012,1950.0,,0.4,0,,,,,,,
119,Senate,13,2,0,CC,328,,,"HALE, Hal",H000013,1950.0,,-0.3,0,,,,,,,
"""
S_ROLLCALLS = """congress,chamber,rollnumber,date,session,clerk_rollnumber,majority_requirement,yea_count,nay_count,nominate_mid_1,nominate_mid_2,nominate_spread_1,nominate_spread_2,nominate_log_likelihood,bill_number,vote_result,vote_desc,vote_question,dtl_desc
119,Senate,1,2025-01-20,1,12,1/2,2,1,0,0,0,0,0,S5,Passed,Senate split,On Passage,
119,Senate,2,2025-01-21,1,13,1/2,1,2,0,0,0,0,0,PN7,Rejected,A nominee,On the Nomination,
"""
S_VOTES = """congress,chamber,rollnumber,icpsr,cast_code,prob
119,Senate,1,11,1,99
119,Senate,1,12,6,99
119,Senate,1,13,1,99
119,Senate,2,11,6,99
119,Senate,2,12,1,99
119,Senate,2,13,1,99
"""
LEGISLATORS = [
    {"id": {"bioguide": "A000001", "fec": []}, "name": {"first": "Alice", "last": "Adams", "official_full": "Alice Adams"}, "terms": [{"type": "rep", "state": "AA", "district": 1, "party": "Democrat"}]},
    {"id": {"bioguide": "B000002", "fec": []}, "name": {"first": "Robert", "nickname": "Bob", "last": "Baker", "official_full": "Robert Baker"}, "terms": [{"type": "rep", "state": "AA", "district": 2, "party": "Democrat"}]},
    {"id": {"bioguide": "C000003", "fec": []}, "name": {"first": "Carla", "last": "Cruz"}, "terms": [{"type": "rep", "state": "AA", "district": 3, "party": "Republican"}]},
    {"id": {"bioguide": "D000004", "fec": []}, "name": {"first": "Dan", "last": "Diaz"}, "terms": [{"type": "rep", "state": "AA", "district": 4, "party": "Republican"}]},
    {"id": {"bioguide": "E000005", "fec": ["H6AK01092"]}, "name": {"first": "Eve", "last": "Evans"}, "terms": [{"type": "rep", "state": "AA", "district": 5, "party": "Independent", "caucus": "Republican"}]},
    {"id": {"bioguide": "F000011", "fec": []}, "name": {"first": "Fay", "last": "Fox"}, "terms": [{"type": "sen", "state": "BB", "party": "Democrat"}]},
    {"id": {"bioguide": "G000012", "fec": []}, "name": {"first": "Gus", "last": "Gray"}, "terms": [{"type": "sen", "state": "BB", "party": "Republican"}]},
    {"id": {"bioguide": "H000013", "fec": []}, "name": {"first": "Hal", "last": "Hale"}, "terms": [{"type": "sen", "state": "CC", "party": "Independent", "caucus": "Democrat"}]},
]


def vote_texts():
    return {"H_members": H_MEMBERS, "H_rollcalls": H_ROLLCALLS, "H_votes": H_VOTES,
            "S_members": S_MEMBERS, "S_rollcalls": S_ROLLCALLS, "S_votes": S_VOTES,
            "legislators": json.dumps(LEGISLATORS)}
