# Changelog

## Unreleased

### Languages
- Feeds can be in other languages (`lang:` in feeds.yaml). Their articles are
  matched against the English keywords plus the language's own list under
  `keywords:`; in Spanish and Portuguese bare "enclave" doesn't count.
- Non-English titles are translated into English with the claude CLI (cached
  in `translations.json`) and shown with the original after them.
  `--no-translate` turns this off.
- Article text fetched without a declared charset is decoded from the page's
  own `<meta charset>`, so accented text matches.

### Coverage
- Spanish feeds from Spain and Latin America, Portuguese feeds from Brazil
  and Portugal, and Google News searches in both languages.

## 2.11.0 — 2026-10-29

### Deduplication
- Articles are dropped as duplicates only when they are copies: the same
  URL, the same outlet and title, or the same text (syndication). Different
  outlets' reports of one story are all kept; previously similar titles from
  different outlets were enough to drop one. Text is fetched only for pairs
  with similar titles. Each copy removed is logged.

### Coverage
- Australian and New Zealand feeds: iTnews, ARN, iTWire, IT Brief and
  SecurityBrief (AU and NZ editions), Reseller News NZ, CIO New Zealand, and
  Google News searches of CRN Australia, Cyber Daily, InnovationAus,
  Information Age and Capital Brief, whose own feeds are gone. Also Google
  News Australia and New Zealand editions of the confidential computing
  search.

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
