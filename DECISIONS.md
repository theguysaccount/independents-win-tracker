# DECISIONS

D1. **Machine-driven, static, keyless.** GitHub Pages plus an hourly Actions job. Python standard library only, because local Python is 3.9 with no node and runners have Python. There is no server; every page is prebuilt HTML that works without JavaScript.

D2. **Name: "Independents Tracker", not "Independents Win".** Independents Win PAC assembled the convention's slate. A site called "Independents Win" would look affiliated with the PAC. The repository keeps its required name, and every page and the About page state that the site has no affiliation.

D3. **Scope: federal independents that a market lists.** A page needs two things: an FEC 2026 statutory House or Senate candidate with an independent or no-party label (IND, NPA, NNE, UN, NON, NOP, N, OTH), and a Kalshi or Polymarket outcome that names them. The other route is a generic "independent" outcome in a race where they are the only independent above $100k. FEC registration alone doesn't show ballot access, and a market listing is the best automatic signal. The 120 other independent filers go in a table with an explicit caveat. That avoids thin pages and wrong claims about ballot status.

D4. **The slate is a tag, not the frame.** The note asked for "the 7 candidates named by the Independent National Convention". They are tagged "INC '26 slate" with a source link (The Fulcrum, Oct. 14, 2026). All of them get pages, including Zabel, whom no market lists. Ordering is by market price, never by slate membership. This settles Jack's open question on which 7 candidates. "RockTheBoat" is not used as a brand, because whether it is a brand or a coalition is unconfirmed.

D5. **No governors in v1.** Their money is filed with the states. The markets still list Mike Duggan (Michigan), who withdrew on May 21, 2026. State races need a curated, sourced list, and a human or a later session must check it first.

D6. **No polling average in v1.** FiveThirtyEight's poll database closed in 2025. Scraping RealClearPolling or similar sites breaks their terms, and Wikipedia tables are fragile and carry CC BY-SA terms. The methodology page says so.

D7. **Implied chance = midpoint if the spread is at most 10¢, else the last trade.** That is Polymarket's own display rule, applied to both venues for comparability. Thin markets (under $25k traded) are flagged. Each card quotes the market's exact question, because NE and MT on Polymarket ask "will an independent win", not about the person.

D8. **Party-line score = CQ party unity.** The score counts only roll calls where a majority of Democrats opposed a majority of Republicans, yea and nay votes only. Party switchers get one record per party, as Voteview does (Kiley: 93.8% as R, 86.9% as I with R). Independents are scored against their caucus from congress-legislators. Ranks need 50 or more such votes, and delegates are excluded.

D9. **Git-scraped snapshots.** Hourly data commits to `data/` give an audit trail for every number and keep the 60-day schedule timer fresh. Raw FEC and Voteview files are not committed, only derived JSON. History is hourly for 14 days and daily before that.

D10. **Discovery daily, reads hourly.** A full Kalshi scan (61 pages) runs once every 20 hours or when the FEC file changes. Hourly runs read only the tracked events, about 30 requests.

D11. **No market bulk downloads.** The CSV on /data carries only the FEC money and the implied price at build time. History lives in the repository for the charts. If either platform objects, `config/tracker.json` → `sources_enabled` switches that source off.

D12. **No gendered pronouns in generated text.** Templates use names or "the member", and a test enforces it.

D13. **Embeds and share.** Each candidate and member gets an SVG badge. Share cards are 1200×630 PNGs rendered by headless Chrome on the runner, with a committed fallback. Share buttons are plain intent links, and nothing is posted.

## Open questions for Jack (none block v1)
1. Is `independentsday.com` yours? It's registered at GoDaddy, and your portfolio is at Namecheap. If yes, it is the natural domain.
2. Should state races (governor) be added with a hand-checked list?
3. Should this live on Independence.org, or stay standalone and neutral? Standalone is recommended, so it can still be cited as neutral.
