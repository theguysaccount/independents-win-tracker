"""Unit tests for the data pipeline: FEC parsing, market matching, party-line scoring."""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fixtures as F  # noqa: E402
from tracker import common, fec, markets, votes  # noqa: E402


class CommonTest(unittest.TestCase):
    def test_person_name(self):
        self.assertEqual(common.person_name("OSBORN, DAN"), "Dan Osborn")
        self.assertEqual(common.person_name("ACHILLES, TODD BAKER"), "Todd Achilles")
        self.assertEqual(common.person_name("BEGICH, NICHOLAS III"), "Nicholas Begich III")
        self.assertEqual(common.person_name("KING, Angus Stanley, Jr."), "Angus King Jr.")
        self.assertEqual(common.person_name("EISENHAUER, MICHAEL D. DR."), "Michael Eisenhauer")
        self.assertEqual(common.person_name("MCDERMOTT, JIM"), "Jim McDermott")

    def test_surname_and_given(self):
        self.assertEqual(common.surname("Todd Achilles (I)"), "achilles")
        self.assertEqual(common.surname("ACHILLES, TODD BAKER"), "achilles")
        self.assertEqual(common.surname("Nick Begich III"), "begich")
        self.assertEqual(common.surname("Mayra Macías"), "macias")
        self.assertEqual(common.given("Nick Begich III"), "nick")

    def test_pct(self):
        self.assertEqual(common.pct(0.255), "25.5%")
        self.assertEqual(common.pct(0.26), "26%")
        self.assertEqual(common.pct(0.0004), "<0.1%")
        self.assertEqual(common.pct(0.9996), ">99.9%")
        self.assertEqual(common.pct(None), "n/a")

    def test_money_and_races(self):
        self.assertEqual(common.money(11029845.41), "$11.0M")
        self.assertEqual(common.money(272259.88), "$272K")
        self.assertEqual(common.money(-656404), "-$656K")
        self.assertEqual(common.race_key("NE", "S"), "NE-S")
        self.assertEqual(common.race_key("AK", "H", "0"), "AK-H-00")
        self.assertEqual(common.race_label("CA", "H", "06", short=True), "CA-06")
        self.assertEqual(common.race_label("AK", "H", "00"), "Alaska at-large U.S. House seat")


class FecTest(unittest.TestCase):
    def setUp(self):
        w, n = F.fec_texts()
        self.out = fec.build(w, n, F.CFG, {"weball": {"last_modified": "x"}})

    def test_filters_to_this_cycle_statutory_candidates(self):
        c = self.out["candidates"]
        self.assertIn("S4NE00207", c)
        self.assertNotIn("S4VT00033", c, "a senator elected in another cycle is not a 2026 candidate")
        self.assertNotIn("H6TX99999", c, "not yet a statutory candidate")

    def test_independent_flags_and_money(self):
        o = self.out["candidates"]["S4NE00207"]
        self.assertTrue(o["independent"])
        self.assertEqual(o["race"], "NE-S")
        self.assertEqual(o["cvg_end"], "2026-10-14")
        self.assertAlmostEqual(o["coh"], 1953183.30)
        self.assertFalse(self.out["candidates"]["S6NE00129"]["independent"])

    def test_races_group_every_candidate_in_independent_races(self):
        self.assertEqual(self.out["races"]["NE-S"][0], "S6NE00129", "sorted by receipts")
        self.assertIn("S4NE00207", self.out["races"]["NE-S"])
        self.assertIn("ID-H-01", self.out["races"])

    def test_no_addresses_in_output(self):
        blob = repr(self.out)
        self.assertNotIn("PRIVATE ST", blob)
        self.assertNotIn("SOMEWHERE", blob)


class MarketsTest(unittest.TestCase):
    def setUp(self):
        w, n = F.fec_texts()
        self.fec = fec.build(w, n, F.CFG, {})

    def test_kalshi_race_titles(self):
        self.assertEqual(markets.kalshi_race("Nebraska Senate winner?"), "NE-S")
        self.assertEqual(markets.kalshi_race("Who will win the Senate race in Oklahoma?"), "OK-S")
        self.assertEqual(markets.kalshi_race("Alaska House winner?"), "AK-H-00")
        self.assertEqual(markets.kalshi_race("CA-06 House winner?"), "CA-H-06")
        self.assertEqual(markets.kalshi_race("NE-01 House winner?"), "NE-H-01")
        self.assertIsNone(markets.kalshi_race("Democratic nominee for Senate in Nebraska?"))
        self.assertIsNone(markets.kalshi_race("Idaho's 1st District margin of victory"))
        self.assertIsNone(markets.kalshi_race("Maine Governor winner?"))

    def test_implied_price_rule(self):
        self.assertEqual(markets.implied(0.25, 0.26, 0.30), 0.255)
        self.assertEqual(markets.implied(0.10, 0.40, 0.30), 0.30, "wide spread: last trade")
        self.assertEqual(markets.implied(None, 0.40, 0.30), 0.30)

    def test_kalshi_record_matches_the_independent(self):
        rec = markets.kalshi_race_record(F.kalshi_event_ne(), "NE-S", self.fec, 0.1)
        by = {o["label"]: o for o in rec["outcomes"]}
        self.assertEqual(by["Dan Osborn"]["cand_id"], "S4NE00207")
        self.assertEqual(by["Dan Osborn"]["price"], 0.255)
        self.assertEqual(by["Pete Ricketts"]["cand_id"], "S6NE00129")
        self.assertEqual(rec["outcomes"][0]["label"], "Pete Ricketts", "sorted by price")
        self.assertEqual(rec["url"], "https://kalshi.com/markets/senatene")

    def test_name_variants_match(self):
        rec = markets.kalshi_race_record(F.kalshi_event_ak(), "AK-H-00", self.fec, 0.1)
        by = {o["label"]: o for o in rec["outcomes"]}
        self.assertEqual(by["Nick Begich III"]["cand_id"], "H2AK01083", "Nick vs NICHOLAS")
        self.assertEqual(by["Bill Hill"]["cand_id"], "H6AK01092")

    def test_polymarket_generic_independent_outcome(self):
        rec = markets.poly_race_record(F.poly_event_ne(), "NE-S", self.fec, 0.1)
        labels = [o["label"] for o in rec["outcomes"]]
        self.assertNotIn("Person B", labels, "placeholder rows are skipped")
        ind = next(o for o in rec["outcomes"] if o["label"] == "Independent")
        self.assertTrue(ind["party_outcome"])
        self.assertEqual(ind.get("covers"), "S4NE00207", "the only independent with real money")
        self.assertEqual(ind["price"], 0.255)
        self.assertEqual(ind["token"], "111")

    def test_resolved_kalshi_market(self):
        ev = F.kalshi_event_ne()
        ev["markets"][1].update(status="settled", result="yes")
        rec = markets.kalshi_race_record(ev, "NE-S", self.fec, 0.1)
        osb = next(o for o in rec["outcomes"] if o["label"] == "Dan Osborn")
        self.assertEqual(osb["price"], 1.0)
        self.assertEqual(osb["result"], "yes")

    def test_best_per_race_keeps_higher_volume(self):
        a = {"source": "kalshi", "race": "NE-S", "id": "A", "outcomes": [{"volume": 10}]}
        b = {"source": "kalshi", "race": "NE-S", "id": "B", "outcomes": [{"volume": 99}]}
        self.assertEqual([r["id"] for r in markets.best_per_race([a, b])], ["B"])

    def test_compact_history(self):
        now = datetime(2026, 10, 25, 21, tzinfo=timezone.utc)
        rows = []
        for h in range(24 * 30):
            t = now - timedelta(hours=h)
            rows.append({"ts": common.iso(t), "source": "kalshi", "market": "M", "price": "0.5"})
        out = markets.compact_history(rows, now)
        recent = [r for r in out if common.parse_iso(r["ts"]) >= now - timedelta(days=14)]
        older = [r for r in out if common.parse_iso(r["ts"]) < now - timedelta(days=14)]
        self.assertEqual(len(recent), 14 * 24 + 1)
        self.assertLessEqual(len(older), 17, "one point per day before the hourly window")


class VotesTest(unittest.TestCase):
    def setUp(self):
        self.out, self.rc = votes.build(F.vote_texts())
        self.by = {m["bioguide"]: m for m in self.out["members"]}

    def test_party_unity_votes_detected(self):
        self.assertEqual(self.out["chambers"]["House"]["party_unity_votes"], 3, "the unanimous vote is not a party-line vote")
        self.assertEqual(self.out["chambers"]["Senate"]["party_unity_votes"], 2)

    def test_scores(self):
        self.assertEqual(self.by["A000001"]["spells"][0]["score"], 1.0)
        bob = self.by["B000002"]["spells"][0]
        self.assertEqual((bob["pu_cast"], bob["missed"]), (2, 1), "a missed vote is not counted against the member")
        self.assertEqual(self.by["B000002"]["name"], "Bob Baker", "nickname from congress-legislators")

    def test_party_switcher_gets_one_record_per_party(self):
        eve = self.by["E000005"]
        self.assertEqual([s["party"] for s in eve["spells"]], ["R", "I"])
        r, i = eve["spells"]
        self.assertEqual((r["pu_cast"], r["with_own"], r["breaks"]), (1, 0, ["H-1"]))
        self.assertEqual(i["own"], "R", "an independent is scored against the caucus")
        self.assertEqual((i["pu_cast"], i["with_own"], i["with_d"], i["with_r"]), (2, 1, 1, 1))
        self.assertEqual(eve["party_now"], "Independent")
        self.assertEqual(eve["fec_ids"], ["H6AK01092"])

    def test_senate_independent_caucus(self):
        hal = self.by["H000013"]["spells"][0]
        self.assertEqual(hal["own"], "D")
        self.assertEqual(hal["score"], 0.5)
        self.assertEqual(hal["breaks"], ["S-2"])

    def test_rollcall_links(self):
        r = self.rc["H-1"]
        self.assertEqual(r["url"], "https://clerk.house.gov/Votes/20255")
        self.assertEqual(r["vv"], "https://voteview.com/rollcall/RH1190001")
        self.assertEqual(r["bill_url"], "https://www.congress.gov/bill/119th-congress/house-bill/1")
        s = self.rc["S-2"]
        self.assertEqual(s["url"], "https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00013.htm")
        self.assertEqual(s["bill_url"], "https://www.congress.gov/nomination/119th-congress/7")
        self.assertEqual(votes.bill_label("HJRES12"), "H.J.Res. 12")
        self.assertEqual(votes.bill_url("SCONRES3"), "https://www.congress.gov/bill/119th-congress/senate-concurrent-resolution/3")

    def test_ranks_need_enough_votes(self):
        for m in self.out["members"]:
            for s in m["spells"]:
                self.assertNotIn("rank_low", s, "fixture members have far fewer than 50 party-line votes")


if __name__ == "__main__":
    unittest.main()
