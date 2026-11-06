# Changelog

## Unreleased

### Scheduling
- The weekly edition is now started by `webfeed-due.sh`, checked hourly from
  cron, instead of a single Thursday 13:00 cron line. A run that is missed,
  killed (the 2026-11-05 run was cut off by a reboot for an OS update) or
  fails is retried every hour until an edition is written.
- `webfeed-run.sh` writes the crawler's output to the log unbuffered, and adds
  a closing line with the exit status and duration, so a killed run is visible
  in `webfeed-cron.log`.

### Matching
- Links in Google News summaries no longer count as a mention of Google.
  Every Google News entry that named no earlier-listed member was filed as
  "about Google" (1,109 of 1,633 matching stored entries), which moved it
  up the edition and left it out of the subjects file.
- Bare "SEV" counts only with AMD or virtualisation context nearby, and
  severity levels (SEV1, SEV-2) never count. Incident-severity jargon
  ("agent accelerated SEVs") had matched an InfoQ panel on frontend
  architecture. SEV-SNP and SEV-ES are unaffected.
- Keywords inside package names (lowercase, three or more hyphen-joined
  parts, e.g. `aws-nitro-enclaves-cli`) are ignored. LWN's daily "Security
  updates for ..." tables matched on them every week.

### Speed
- Article text for entries whose title and summary don't match is now
  fetched in parallel after all feeds are read, at most 2 requests per server
  (IP address) at a time. With a week of stored entries (~10,700 fetches)
  this takes ~9 minutes instead of an estimated 6-9 hours. The report is
  unchanged: entries keep their feed order, so duplicate removal keeps the
  same copy.
- The hourly `--store-only` run now also fetches and saves the article text
  that the weekly run would check (`feed-store/texts/`, kept 14 days), at
  most 1,500 articles per run. The weekly run takes text from there and
  fetches only what's missing, so it takes minutes and spreads the load on
  each site across the week.
- `polite_hosts:` / `polite_delay:` in feeds.yaml: article fetches to a
  listed site's server go one at a time with a pause. Used for TechDay
  (IT Brief / SecurityBrief), whose feeds are paused after it blocked us.
- `python-dateutil` added to requirements.txt.

### Languages
- Feeds can be in other languages (`lang:` in feeds.yaml). Their articles are
  matched against the English keywords plus the language's own list under
  `keywords:`; in Spanish and Portuguese bare "enclave" doesn't count.
- Non-English titles are translated into English with the claude CLI (cached
  in `translations.json`) and shown side by side with the original, English
  first, both inside the link: "[English / original](url)".
  `--no-translate` turns this off.
- Article text fetched without a declared charset is decoded from the page's
  own `<meta charset>`, so accented text matches.
- Japanese: 20 feeds (ITmedia, Impress Watch, @IT, Publickey, ASCII.jp,
  Nikkei xTECH, Security NEXT, ScanNetSecurity and others, plus Google News
  searches), with Japanese keywords. Matching normalises full-width
  characters, ignores spaces and ・ in Japanese, and no longer needs a word
  break after an acronym ("TDXを"). Member names in katakana and kanji count
  as member mentions (`MEMBER_ALIASES`). A past-week test found 4 stories,
  all via Google News.
- Korean: 20 feeds (Electronic Times, ZDNet Korea, Daily Secu, Digital
  Today, IT Chosun, Bloter, TechM, The Elec Korean, Byline Network,
  Datanet, iNews24, AI Times and others; Boan News, Digital Daily, Digital
  Times and ITWorld Korea via Google News site searches; two Google News CC
  searches), with Korean keywords, matched ignoring spaces. Korean context
  words, member names (인텔, 삼성전자, 오페이크 ...) and "싱가포르 거래소
  (SGX)" are handled as in Japanese. Feeds from Korean CMSs with zone-less
  dates use `timezone: Asia/Seoul`. A past-week test found 1 story, via
  Google News.

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
