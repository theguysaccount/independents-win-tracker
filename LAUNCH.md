# LAUNCH

**Launch URL (live):** https://theguysaccount.github.io/independents-win-tracker/. No DNS change
is needed. Custom-domain steps and the exact records are in [OPERATIONS.md](OPERATIONS.md#keys-a-human-can-turn-later).

The venture is machine-driven, so nothing is posted as anyone and no outreach is drafted for a
human to send. Distribution runs on machine channels built into the product.

## Distribution built in

1. **Search pages for real queries.**
   - One page per candidate, titled "<name> odds and money: <race> 2026". It answers "dan osborn odds", "nebraska senate odds", "bill hill alaska odds" and "seth bodnar polymarket".
   - One page per member, titled "<name>: votes with the <party> majority X%". It answers "<member> votes with party", "<member> voting record" and "most bipartisan senators".
   - Index pages for "independent candidates 2026", "party line voting scores" and "party unity scores 119th congress".
2. **Structured data**: ProfilePage and Person on every candidate and member page, Dataset on /data (for Google Dataset Search), BreadcrumbList everywhere.
3. **IndexNow**: every deploy that adds pages, plus a daily resubmission, pushes all URLs to Bing, Yandex, Seznam and Naver.
4. **Sitemap and canonical URLs** on every page. Robots.txt is ready for a root domain.
5. **Share loop**: a 1200×630 card per candidate showing live odds and money, a native share sheet, and Bluesky, X, Facebook and LinkedIn intent links. Each share carries a sourced one-line summary.
6. **Embeddable badges**: `/badge/<candidate>.svg` and `/badge/m/<member>.svg`. They update every hour, so campaigns, newsletters and READMEs that paste one keep linking back.
7. **Atom feed** of daily closing odds for every tracked independent (`/feed.xml`), for feed readers and aggregators.
8. **GitHub discoverability**: a public repo with a description, topics (elections, prediction-markets, kalshi, polymarket, fec, congress, voteview, open-data) and CC0 data that others can cite.

## First 1,000 visitors: where they come from (no outreach)

- Election week (Oct. 27 – Nov. 4): searches for each of the 11 candidates' odds and the 4 Senate races with independents (NE, MT, SD, ID), plus Alaska at-large and CA-06. These are long-tail queries with weak competition, because the market sites themselves rank for the market pages, not for "odds and money".
- Election night: "how many independents won" and the resolved markets.
- After the election: member pages carry the evergreen traffic ("votes with party", 555 pages) and are recomputed whenever Voteview adds votes.
- Embeds: each badge on a third-party page is a backlink and a visit source.

## Calendar (automatic)

| When | What happens without anyone |
|---|---|
| Twice an hour (:17, :47) | Prices reread, pages rebuilt, snapshot committed; a watchdog (:05, :35) restarts the update if GitHub skipped it |
| Daily 09:17 UTC | IndexNow resubmission of every URL |
| Every 20 h | Market rediscovery (new independents appear automatically) |
| Nightly (FEC) | New money totals once the FEC file changes |
| When Voteview publishes | Party-line scores recomputed for every member |
| Mondays | Self-test of every live URL and of data freshness |
| Nov. 3–4 | Markets resolve and cards switch to "Resolved YES/NO" |
