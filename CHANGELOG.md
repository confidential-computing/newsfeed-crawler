# Changelog

## 2.10.0 — 2026-10-29

### Webfeed editions
- Editions are CMS posts: YAML frontmatter (title, post_status, post_date,
  taxonomy category `newsfeed`) and plain article lists, with no section
  headings, member details or per-article tags.
- Groups of articles about the same story no longer get a bold title in
  editions; their articles are listed next to each other as plain bullets.
- `--webfeed-exclude-uk` drops articles from UK outlets.

### Coverage
- New Asian feeds (Singapore, Malaysia, Taiwan, Hong Kong, China, Japan,
  Korea, India), plus regional Google News editions and a second Google News
  search for terms related to confidential computing.
- Articles are tagged with their outlet's region (not shown in reports);
  `--exclude-region` and `--only-region` filter on it.
- Feed entries are saved between runs: `--store-only`, run hourly from cron,
  saves every feed's entries to `feed-store/` (kept 35 days), and every crawl
  merges them with what each feed shows live. Feeds that only list a few hours
  of items are now covered for the whole week, and a feed that fails to load
  still contributes its stored entries. Saving pauses with a logged error if
  the disk is more than 80% full (`--entry-store-disk-limit`).
- Feeds can set `timezone:` for dates that carry no zone.
- Fixed feeds: DigiTimes Asia and Times of India now come through Google News
  searches, InfoQ uses its main feed, and BusinessKorea and The Elec dates are
  read as Korean time, not UTC. The SUSE blog is read from its JSON API.
- Google News is asked for one day past the window end, because it truncates
  results when the end date is today.

### Matching
- New keywords: `confidential AI` and `trusted execution environment`.
  Plurals match (`TEEs`, `enclaves`, `confidential VMs`).
- `enclave` and bare `SGX` count only with computing context within 80
  characters, so territorial enclaves and the Singapore Exchange are ignored.

### Other
- `--version`.

## 2.9.0 — 2026-09-24

- Webfeed editions are numbered per day (`webfeed-DATE-NN.md`), so a second
  run never overwrites the first.
