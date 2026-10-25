# PRODUCT

**User.** Independent-curious voters, journalists and campaign watchers asking, in the last days before Nov. 3, 2026, "can independents actually win, and which ones?". After the election, anyone searching "how often does <member> vote with their party".

**Painful job.** The answer is scattered. Kalshi and Polymarket each list some races, the money sits in FEC filings, and voting records sit on Voteview or the Clerk's site. Nobody puts the independents in one place with sources.

**Promise.** One page per independent with live odds from both markets and the campaign's money, plus a party-line score for every member of Congress. Every number is sourced and dated.

**Wedge.**
- Pages built for real queries: "<candidate> odds", "<state> senate odds independent", "<member> votes with party".
- Embeddable live badges and share cards that campaigns and newsletters can paste.
- A daily feed.

**Why now.** Election Day is Nov. 3, 2026. Markets price four independent Senate bids (Osborn 26%, Bodnar 8%, Bengs 5%, Achilles 4%) and two House races (Hill 21%, Kiley 6%). The party-line index stays useful after the election.

**Activation metric.** A visitor on a candidate or member page who clicks a source link, shares, or copies the embed code. These are instrumented as `source-*`, `share` and `embed-copy` events, and record once a GoatCounter endpoint is set (see OPERATIONS.md).

**First revenue event.** None in v1, which is informational by design. One footer slot (`SUPPORT_URL`) takes a GitHub Sponsors or grant link for upkeep, and it is never a donation link for a candidate.

**v1 deliberately won't:**
- Endorse, rank candidates on merit, or link donations to candidates.
- Show polls (no open feed).
- Cover governors.
- Predict outcomes beyond what the markets say.
- Collect personal data.
