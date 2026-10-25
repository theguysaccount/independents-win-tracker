# STATE: 2026-10-25

**Before this session:** two Apple Notes (Sept. 25–26, 2026), no code, no site. The "7 candidates named by the Independent National Convention" are the 2026 Independent Slate (Independents Win PAC), per The Fulcrum, Oct. 14, 2026.

**Works now:**
- Live on GitHub Pages: 11 candidate pages, 555 member pages, the candidates and party-line indexes, methodology, data and about pages, sitemap, feed, badges and share cards.
- Market discovery scans all ~12,000 open Kalshi events and the Polymarket race events, and matches outcomes to FEC independents by race and name. It finds Osborn, Hill, Bodnar, Kiley, Bengs, Achilles, Getty, Ahlman, Bridgford and Macías. Zabel has a page from the slate but no market lists her.
- Party-line scores for every member of the 119th Congress come from Voteview, with party switchers (Kiley) and caucus-based scoring for independents (Sanders, King, Kiley).
- An hourly job (refresh, test, build, guard, deploy, commit snapshot, IndexNow), a weekly self-test, keep-alive in both, and 31 tests.

**Known gaps:**
- No polling average: no open, licensed 2026 polls feed exists.
- Governors and state races are out: their money is filed with the states, and markets still list withdrawn candidates such as Duggan in Michigan.
- Ballot status comes from market listings, not from state election offices.
- Google can't see the sitemap. The project's robots.txt sits under a path, and only a custom domain or an account-root site fixes that.

**Worth reusing:** `tracker/votes.py`, a party-unity engine on Voteview CSVs with official-record links (the matcher reuses it). Also `tracker/markets.py` (Kalshi and Polymarket readers with a common implied-price rule) and `tracker/guard.py` (pre-deploy link, source and neutrality checks).
