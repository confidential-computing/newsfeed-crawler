# Deduplication

Reports and webfeed editions list each *article* once, but keep every
outlet's report of a *story*. If two outlets write up the same announcement
in their own words, both stay. If one outlet's text appears twice
(syndication, or one article reached through two feeds), only the first copy
stays.

## Rules

`deduplicate_articles()` in `crawler.py` runs after collection and before
clustering, across all three categories (by member, about a member, other).
Articles are taken in that order, and the first copy is the one kept.

A later article is a copy of one already kept when:

1. **The URLs are the same** once normalised. Tracking parameters
   (`utm_*`, `fbclid`, …), fragments and case are ignored.
2. **The titles are similar** (Jaccard ≥ `DEDUP_TITLE_SIMILARITY`, 0.6, on
   title tokens, ignoring the " - Publisher" suffix Google News adds) **and**
   either
   - **the same outlet** published both under the same title, e.g. one
     article seen through two Google News editions. For Google News links
     the outlet is taken from the entry's `<source>` (the article's `host`).
     An outlet's regional editions count as one outlet (`ca.investing.com`
     and `in.investing.com` are both `investing.com`), or
   - **the texts are the same**: at least `DEDUP_TEXT_OVERLAP` (80%) of the
     5-word phrases of the shorter text also appear in the other. Syndicated
     copies, such as IT Brief Australia republishing an IT Brief Asia story,
     score close to 100%. Two outlets writing up the same press release score
     far lower.

The text check is lazy. Article text is fetched only for pairs whose titles
are similar, and once per URL. If either text can't be read, the pair isn't
judged to be copies and both are kept. Texts can be unreadable because of
Google News redirect links, paywalls, or pages shorter than
`DEDUP_MIN_SHINGLES` (40) phrases. Different outlets' reports of the same
story are never collapsed, so they still appear side by side in their story
cluster.

Each copy removed is logged:

```
Deduplicating articles...
  copy: 'Vendor X launches confidential AI service' (IT Brief Australia) = IT Brief Asia
  Removed 1 copies of articles already listed.
```

`--no-dedup` turns deduplication off.

## Tests

```bash
python3 test_deduplication.py             # unit tests, no network
python3 test_real_world_duplicates.py
python3 test_known_duplicates_integration.py
```

The tests pass a stub in place of `fetch_article_text` and never fetch their
made-up URLs.
