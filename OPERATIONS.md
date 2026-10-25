# OPERATIONS

Everything here runs on GitHub Actions in `theguysaccount/independents-win-tracker`, and no human
needs to be involved. The live site is https://theguysaccount.github.io/independents-win-tracker/.

## Automated jobs

| Workflow | When | What it does | How it fails safely |
|---|---|---|---|
| `update.yml` | Hourly at :17 UTC, on every push to `main` (code), and by hand | 1. `tracker.refresh` rereads the Kalshi and Polymarket prices for the tracked races. It HEAD-checks the FEC bulk files and the Voteview CSVs and downloads them only when they changed. It rediscovers markets every 20 hours or when the FEC file changes. 2. Runs the test suite. 3. Builds the site and share cards. 4. `tracker.guard` checks it. 5. Deploys to Pages. 6. Commits the `data/` snapshot. 7. Pings IndexNow when pages were added or removed, and daily at 09:xx UTC. 8. Keep-alive. | Each source is read on its own. A failed source keeps its last good file, and `data/status.json` records the error. Pages print each dataset's own read time, so stale numbers never pass as new. A failed test or guard stops before deploy, so the last good site stays live. Data pushes retry three times, then give up for the hour. An IndexNow failure is ignored. |
| `selftest.yml` | Mondays 10:23 UTC, and by hand | 1. Runs the full test suite. 2. `tracker.refresh --check-fresh` fails if a source has had no successful read in 6 h (markets) or 3 days (FEC, Voteview). 3. `tracker.selftest` fetches every sitemap URL plus assets, checks the 200s, checks candidate pages carry their sources, and checks the live market read time is under 6 h old. 4. Keep-alive. | Read-only against the site. A failure only sends GitHub's failure email to the repository owner. |
| `test.yml` | Pull requests and pushes to non-main branches | Tests on Python 3.9 and 3.12, then a build and guard | Never deploys |

**Keep-alive.** GitHub pauses scheduled workflows in public repositories after 60 days without
repository activity. Hourly data commits normally prevent that. As a backstop, each scheduled run
re-enables both scheduled workflows through the API (`PUT /actions/workflows/{id}/enable`). It also
pushes an empty `keep-alive` commit if the last commit is older than 45 days, which can happen after
the markets resolve and Congress is in recess.

## What to watch

- **Actions tab → "Update and deploy".** A red run means the site was *not* updated that hour. The previous site is still live. Read the failing step: Tests, Guard (its log lists each problem), or Refresh.
- **`data/status.json`**: per source, `ok`, `last_success`, `error`, `note`. It shows a source that keeps failing even while the site still deploys.
- **"Weekly self-test" failures**: the live site is unreachable, a page is broken, or a source has been failing for longer than its limit.
- **After Election Day**: markets resolve (`result: yes/no`), and cards then show "Resolved YES/NO". Discovery keeps resolved markets. Hourly reads can be reduced to daily by changing the cron to `17 9 * * *` in `update.yml` once all markets have resolved. Nothing breaks if it stays hourly.
- **Known data quirks** shown as-is: some FEC records carry odd party codes (Risch "UNK", Burbank "DE"). Race tables use the market's party label when the FEC has none.

## Manual levers (all optional)

- **Run now:** Actions → Update and deploy → Run workflow. Tick "discover" to rescan the markets, or "force" to re-download the FEC and Voteview files.
- **Hide a candidate** (withdrawn, mismatched): add `"<FEC id>": "reason + source URL"` to `exclude` in `config/tracker.json`.
- **Switch a source off** (for example, after a takedown request): set `sources_enabled.kalshi` (or `polymarket`, `fec`, `voteview`) to `false` in `config/tracker.json`. The last data stays until the next refresh replaces it.
- **Change the slate or scope**: `slate`, `fec.independent_codes` and `markets.*` in `config/tracker.json`.

## Keys a human can turn later

None of these is needed for the site to work.

1. **Custom domain.** The best option is `independentstracker.org`, which was unregistered on 2026-10-25 (about $10/yr; buying it needs Jack's OK). `independentsday.com` comes from Jack's notes and is registered at GoDaddy, owner unconfirmed. `tracker.byepartisans.com` is owned (Namecheap) but carries a partisan pun that undercuts neutrality. Steps:
   1. Buy or confirm the domain.
   2. DNS at the registrar. For an apex, add four `A` records `@` → `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`, and `CNAME www` → `theguysaccount.github.io`. For a subdomain, add one `CNAME tracker` → `theguysaccount.github.io`.
   3. Repository Settings → Pages → Custom domain → enter it, wait for the certificate, then tick "Enforce HTTPS".
   4. Settings → Secrets and variables → Actions → Variables: set `SITE_URL=https://<domain>` and edit `update.yml` and `selftest.yml` so `env.SITE_URL` reads `${{ vars.SITE_URL }}`. Run "Update and deploy". Canonicals, sitemap, share cards and IndexNow then follow the domain.
   5. A domain also fixes the one SEO gap: crawlers read `robots.txt` (and its Sitemap line) only at a host's root, which a project path on github.io can't provide.
2. **Money slot (informational, upkeep only).** Set repository variable `SUPPORT_URL` to a GitHub Sponsors page or civic-grant page, and optionally `SUPPORT_LABEL`. The footer link appears on the next hourly run with a "not a political contribution" note. Creating a Sponsors profile needs the account owner (bank and tax forms). Never point it at a candidate, PAC or party: that would end the tracker's neutrality and raise FEC coordination questions.
3. **Analytics (activation metric).** Create a free GoatCounter site, then set repository variable `GOATCOUNTER_URL=https://<code>.goatcounter.com/count`. Page views and the events `share`, `embed-copy` and `source-<kalshi|polymarket|fec|clerk|voteview|congress|slate>` start recording. That needs an account, so it was not done.
4. **Search Console.** Verify the domain in Google Search Console with a DNS TXT record and submit `/sitemap.xml`. Bing and Yandex already get every page through IndexNow.
5. **Recurring written content (optional).** There is no AI key in Actions. To add a daily "what moved" note, schedule a Claude routine that runs once a day after 09:30 UTC. It would read `data/markets.json` and `data/history.csv` from `main`, write `notes/YYYY-MM-DD.md` with the three largest 24-hour moves (each quoting market, price, time and source URL), and open a pull request. The site already publishes a deterministic daily feed (`/feed.xml`) without it.

## Costs

$0. Public repository, GitHub-hosted runners (about 2–3 minutes per hourly run), GitHub Pages and keyless public APIs.
