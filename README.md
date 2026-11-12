# CC-news-crawler

Crawls a curated list of tech-news RSS/Atom feeds for articles about Confidential Computing, then categorises them against the current list of [Confidential Computing Consortium](https://confidentialcomputing.io/) member companies.

Unlike `AG-CC-news`, this project does not depend on Google News — it fetches feeds directly.

**Matching logic:** articles are included only if they match a Confidential Computing keyword. All-uppercase acronyms (`TEE`, `SGX`, `TDX`, `SEV`, `SEV-SNP`) are matched case-sensitively with word boundaries; multi-word phrases (`confidential computing`, `confidential AI`, `trusted execution environment`, `remote attestation`, `Arm CCA`) and `enclave` are matched case-insensitively. Plurals match too (`TEEs`, `enclaves`). This avoids false positives like `tee` inside "committee" or `sev` inside "several". `enclave` counts only with computing context nearby, so territorial uses ("the Gaza enclave") are ignored. Matched articles are then sub-categorised by CCC member affiliation.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Runtime dependency:** the `claude` CLI must be on your `$PATH` and authenticated with the LFX MCP integration. The crawler shells out to `claude -p` to refresh `members.json` from LFX at most once per week, and to cluster matched articles into same-story groups. If the `claude` CLI is unavailable or the call fails, a deterministic heuristic (shared company + date proximity + title-token overlap) is used automatically as a fallback.

## Usage

```bash
# Last 30 days, default keywords, write report-YYYY-MM-DD.md
python crawler.py

# Custom date range
python crawler.py --start 2026-04-01 --end 2026-05-01

# Custom keywords and output
python crawler.py --keywords "confidential computing,SGX,SEV,SEV-SNP,TDX,TEE,enclave,Arm CCA,remote attestation" --output my-report.md

# Skip full-article fetching (faster, less thorough)
python crawler.py --no-fetch-articles

# Force re-fetch of CCC members from LFX (bypasses the 7-day TTL)
python crawler.py --force-refresh

# Skip story clustering (render flat lists as before)
python crawler.py --no-cluster

# Use the deterministic heuristic for clustering (no claude CLI call)
python crawler.py --no-ai-cluster
```

## Output

Three-section Markdown report, with articles grouped by story within each section:
- **Articles BY Members** — publisher or author is a CCC member company
- **Articles ABOUT Members** — article text mentions a CCC member
- **Other Articles** — matched CC keywords but no member mention
- **Subject Companies** — summary of non-member companies that appeared most

When multiple outlets cover the same event, those articles are grouped under a bold story label. Standalone articles appear as plain bullets.

A `subjects-YYYY-MM-DD.json` file is also written alongside the report; each article entry includes a `_cluster` field with the story group id.

### Webfeed editions

`--webfeed` editions are grouped by story. Each story is one bullet with its lead article in full (English if there is one, a direct link before a Google News redirect, then the earliest); the rest of its coverage follows as indented lines of outlet-name links, English first, then one line per language with the label in that language too:

```
- [Google TPU 8tx Pairs AMD EPYC Turin Hosts with Confidential Computing…](url) (General CC News) (Publisher: ServeTheHome) - Mon, 09 Nov 2026 21:37:58 UTC
  - More in English (18): [SMBtech](url), [TechTarget](url), …
  - Also in Korean | 한국어로도 (11): [디일렉](url), …
  - Also in Spanish | También en español (7): [MuyComputerPro](url), …
```

Stories with more coverage come first. A story covered by one article stays an ordinary bullet. Grouped editions always ask the `claude` CLI to cluster, with instructions to treat the same news across outlets and languages as one story (the deterministic heuristic, used if that fails, only merges near-identical headlines). `--webfeed-flat` writes the older flat list instead: one bullet per article, same-story articles adjacent.

## Adding feeds

Edit `feeds.yaml` — no code changes needed. Each feed may set `region:` — where the outlet is based (e.g. `us`, `uk`, `global`, `asia`, `in`, `sg`, `kr`), not what the story is about. Regions are not shown in reports; they are recorded per article in the subjects JSON and used for filtering.

A feed whose dates have no time zone (e.g. `2026-10-29 21:48:48`) is read as UTC unless it sets `timezone:` to an IANA zone such as `Asia/Seoul`; dates that state a zone are left alone.

A known outlet domain (built-in `OUTLET_REGIONS` in `crawler.py`, extended by a top-level `outlet_regions:` mapping in `feeds.yaml`) or a country-code TLD (`.com.au`, `.co.kr`, `.in`, …) takes precedence over the feed's `region:`. Google News feeds are tagged per article by the outlet behind each result.

```bash
# Drop articles from UK and Singapore outlets
python crawler.py --exclude-region uk --exclude-region sg

# Only Indian and Korean outlets (articles with no known region are dropped)
python crawler.py --only-region in --only-region kr
```

`--webfeed-exclude-uk` still works and is equivalent to `--exclude-region uk` in webfeed mode.

## Feeds in other languages

A feed sets `lang:` (e.g. `es`, `pt`; default `en`) when its articles aren't in English. Its articles are matched against the English keywords plus the language's list under the top-level `keywords:` mapping in `feeds.yaml`. Acronyms such as TEE, SGX and TDX need no translation. Some English keywords are ordinary words in another language: in Spanish and Portuguese bare "enclave" means a territorial enclave, so there only qualified forms such as "enclave seguro" count. Japanese (`ja`) is matched ignoring spaces and the katakana middle dot (・), so "コンフィデンシャル・コンピューティング" and "コンフィデンシャルコンピューティング" are the same keyword, and full-width letters (ＳＧＸ) count as ordinary ones. Acronyms match with text written straight after them ("TDXを"). Korean (`ko`) is also matched ignoring spaces, because compound nouns are spaced inconsistently (기밀 컴퓨팅 / 기밀컴퓨팅). Members' names as Japanese and Korean articles write them (インテル, 富士通, 인텔) are listed in `MEMBER_ALIASES` in `crawler.py`.

Matched non-English titles are translated into English with the `claude` CLI before deduplication and clustering, so stories are compared in one language. Reports and editions show the English and original titles side by side, English first, both inside the link so readers of either language can click the title they read:

```
- [Microsoft expands confidential computing on Azure / Microsoft amplía la computación confidencial en Azure](https://...) ...
```

Translations are cached in `translations.json` (`--translations-cache`), so each title is translated once. If translation fails, the original title is shown and a warning is printed. `--no-translate` skips translation.

## Stored feed entries

Many feeds list only the last few hours or a day of items, so a weekly run would miss most of their week. `--store-only` fetches every feed and saves new entries to `feed-store/` (one JSON-lines file per UTC day, kept for 35 days), then exits without matching or writing a report. Every normal run merges the stored entries for each feed with what the feed shows live, and still uses stored entries when a feed fails to load.

```bash
# Run hourly from cron; each run takes about a minute
python crawler.py --store-only

# Ignore the store for one run
python crawler.py --no-entry-store
```

If the filesystem holding the store is more than 80% full (`--entry-store-disk-limit`), nothing new is saved: `--store-only` logs an error, removes expired days and exits with status 2 without fetching, and normal runs log the error but still read the stored entries.

`--store-only` also fetches the article text of recently stored entries (first seen in the last 8 days) whose title, summary and tags don't match, and saves it to `feed-store/texts/` (compressed, kept for 14 days). Normal runs take full text from there and fetch only what's missing, so the weekly run no longer fetches ~10,000 pages in one go. A failed fetch is retried by later runs, up to 3 tries in all. Each run fetches at most 1,500 articles, so a backlog is spread over several hours. `--no-fetch-articles` turns this off.

The store-only output lists how far back each feed reaches. If a feed's oldest entry is newer than the time between runs, the runs aren't frequent enough to catch all of its items.

At the end of each run a per-feed yield table (entries live+stored / in window / matched) is printed to stderr, which is useful when judging whether a new feed earns its place.

## Scheduling the weekly edition

`webfeed-due.sh` runs hourly from cron:

```
0 * * * * /path/to/newsfeed-crawler/webfeed-due.sh >/dev/null 2>&1
```

It starts `webfeed-run.sh` (which runs `crawler.py --webfeed --webfeed-exclude-uk`) when no edition has been written since the most recent Thursday 13:00 UTC, according to `last_run_at` in `.webfeed-state.json`. A run that was missed because the machine was off, or that was killed or failed, is therefore retried at the next hour until an edition is written. A late edition resumes from the previous edition's cutoff, so nothing is dropped or repeated. A lock (`.webfeed.lock`) stops a second run from starting while a slow run is still going.

`webfeed-run.sh` appends to `webfeed-cron.log`, with a start line and a `finished (status N, Ns)` line for each run. A start line with no finish line means the run was killed, for example by a reboot.

## Published editions

Weekly editions are published in [confidential-computing/newsfeed](https://github.com/confidential-computing/newsfeed).

## Licence

Apache License 2.0; see [LICENSE](LICENSE).
