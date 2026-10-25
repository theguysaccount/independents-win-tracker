"""End-to-end: build the site from synthetic data and from the committed data, then guard it."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import fixtures as F  # noqa: E402
from tracker import build, common, fec, guard, markets, og, votes  # noqa: E402

NOW = datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)
PRONOUNS = re.compile(r"\b(he|she|him|his|her|hers|himself|herself)\b", re.I)


def make_data_dir(d):
    w, n = F.fec_texts()
    f = fec.build(w, n, F.CFG, {"weball": {"url": "x", "last_modified": "Sun, 25 Oct 2026 05:39:17 GMT"}})
    f["fetched_at"] = "2026-10-25T06:00:00Z"
    common.write_json(os.path.join(d, "fec.json"), f)
    races = [markets.kalshi_race_record(F.kalshi_event_ne(), "NE-S", f, 0.1),
             markets.kalshi_race_record(F.kalshi_event_ak(), "AK-H-00", f, 0.1),
             markets.poly_race_record(F.poly_event_ne(), "NE-S", f, 0.1)]
    agg = [{"source": "polymarket", "id": "how-many-independents-will-be-elected-to-congress",
            "title": "How many Independents will be elected to Congress?", "url": "https://polymarket.com/event/x",
            "outcomes": [{"id": "1", "label": "0", "price": 0.56}, {"id": "2", "label": "1", "price": 0.275}]}]
    common.write_json(os.path.join(d, "markets.json"), {"fetched_at": "2026-10-25T21:00:00Z", "races": races, "aggregates": agg, "errors": []})
    with open(os.path.join(d, "history.csv"), "w") as fh:
        fh.write("ts,source,market,price\n2026-10-24T21:00:00Z,kalshi,SENATENE-26-DOSB,0.2400\n2026-10-25T21:00:00Z,kalshi,SENATENE-26-DOSB,0.2550\n")
    v, rc = votes.build(F.vote_texts(), versions={"H_votes": {"last_modified": "Thu, 01 Oct 2026 07:01:56 GMT"}})
    v["fetched_at"] = "2026-10-25T06:00:00Z"
    common.write_json(os.path.join(d, "votes.json"), v)
    common.write_json(os.path.join(d, "rollcalls.json"), rc)
    common.write_json(os.path.join(d, "status.json"), {})


class FixtureSiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.data = os.path.join(cls.tmp, "data")
        os.makedirs(cls.data)
        make_data_dir(cls.data)
        cls.out = os.path.join(cls.tmp, "site")
        cls._cfg = build.load_config
        build.load_config = lambda: F.CFG
        try:
            cls.site = build.build(out=cls.out, site_url="https://example.test/independents-win-tracker", env={}, now=NOW, data_dir=cls.data)
            find = og.find_chrome
            og.find_chrome = lambda: None  # tests copy the default card instead of launching Chrome
            try:
                og.run(cls.out, cls.site.m)
            finally:
                og.find_chrome = find
        finally:
            build.load_config = cls._cfg

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def read(self, rel):
        with open(os.path.join(self.out, rel), encoding="utf-8") as f:
            return f.read()

    def test_tracked_candidates(self):
        slugs = [c["slug"] for c in self.site.m.candidates]
        self.assertEqual(slugs[0], "dan-osborn", "sorted by market price")
        self.assertIn("bill-hill", slugs)
        self.assertIn("sarah-zabel", slugs, "slate members get a page without a market")
        self.assertNotIn("kshama-sawant", slugs, "no market and not on the slate: listed, no page")

    def test_candidate_page_cites_sources(self):
        html = self.read("candidates/dan-osborn/index.html")
        self.assertIn("25.5%", html)
        self.assertIn("https://www.fec.gov/data/candidate/S4NE00207/", html)
        self.assertIn("https://kalshi.com/markets/senatene", html)
        self.assertIn("https://polymarket.com/event/nebraska-senate-election-winner", html)
        self.assertIn("any</em> independent wins the race", html)
        self.assertIn('<link rel="canonical" href="https://example.test/independents-win-tracker/candidates/dan-osborn/">', html)
        self.assertIn('"@type": "ProfilePage"', html)
        self.assertIn("▲ 1.5", html, "24-hour change from the stored history")

    def test_race_money_uses_market_listed_candidates(self):
        html = self.read("candidates/dan-osborn/index.html")
        section = html.split("Money in this race")[1]
        self.assertIn("Pete Ricketts", section)
        self.assertNotIn("Sasse", section, "a stale FEC record that no market lists stays out")

    def test_member_pages(self):
        html = self.read("party-line/eve-evans-aa/index.html")
        self.assertIn("caucuses with Republicans", html)
        self.assertIn("Before that, as a Republican", html)
        self.assertIn("../../candidates/bill-hill/", html, "a member who is a tracked candidate links to the race")
        self.assertIn("https://clerk.house.gov/Votes/20268", html)

    def test_no_gendered_pronouns_in_generated_text(self):
        for rel in ["index.html", "candidates/dan-osborn/index.html", "candidates/sarah-zabel/index.html",
                    "party-line/eve-evans-aa/index.html", "party-line/hal-hale-cc/index.html"]:
            text, _ = guard.visible_text(self.read(rel))
            self.assertIsNone(PRONOUNS.search(text), f"{rel}: {PRONOUNS.search(text)}")

    def test_seo_files(self):
        sm = self.read("sitemap.xml")
        self.assertIn("https://example.test/independents-win-tracker/candidates/dan-osborn/", sm)
        self.assertNotIn("404", sm)
        self.assertIn("Sitemap: https://example.test/independents-win-tracker/sitemap.xml", self.read("robots.txt"))
        self.assertIn("<svg", self.read("badge/dan-osborn.svg"))
        self.assertIn("Kalshi 25.5%", self.read("badge/dan-osborn.svg"))
        feed = self.read("feed.xml")
        self.assertIn("Dan Osborn (NE Senate): Kalshi 25.5%", feed)

    def test_guard_passes(self):
        mc, mm = guard.MIN_CANDIDATES, guard.MIN_MEMBERS
        guard.MIN_CANDIDATES, guard.MIN_MEMBERS = 1, 1
        try:
            errors, counts = guard.check(self.out)
        finally:
            guard.MIN_CANDIDATES, guard.MIN_MEMBERS = mc, mm
        self.assertEqual(errors, [])

    def test_guard_catches_advocacy_and_broken_links(self):
        path = os.path.join(self.out, "about", "index.html")
        orig = self.read("about/index.html")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(orig.replace("</main>", '<p>Please vote for Dan Osborn.</p><a href="../nowhere/">x</a></main>'))
            errors, _ = guard.check(self.out)
            self.assertTrue(any("advocacy" in e for e in errors))
            self.assertTrue(any("broken link" in e for e in errors))
        finally:
            with open(path, "w", encoding="utf-8") as f:
                f.write(orig)


@unittest.skipUnless(os.path.exists(os.path.join(common.DATA, "votes.json")), "no committed data yet")
class CommittedDataSiteTest(unittest.TestCase):
    """The real snapshot in data/ must always build into a site that passes the guard."""

    def test_build_and_guard(self):
        tmp = tempfile.mkdtemp()
        try:
            site = build.build(out=tmp, env={})
            find = og.find_chrome
            og.find_chrome = lambda: None
            try:
                og.run(tmp, site.m)
            finally:
                og.find_chrome = find
            errors, counts = guard.check(tmp)
            self.assertEqual(errors, [])
            self.assertGreaterEqual(counts["members"], 400)
            with open(os.path.join(tmp, "data", "candidates.csv")) as f:
                self.assertGreater(len(f.read().splitlines()), 5)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
