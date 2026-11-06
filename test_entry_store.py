#!/usr/bin/env python3
"""
Unit tests for the feed entry store in crawler.py
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import feedparser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse

import crawler
from crawler import (EntryStore, TextStore, entry_datetime, localise_naive_dates,
                     merge_stored_entries, store_article_texts, text_store_dir)

FEED = "https://example.com/feed"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def entry(link, published=None, **extra):
    e = feedparser.FeedParserDict(title=f"Title {link}", link=link, summary="s",
                                  author="a", tags=[feedparser.FeedParserDict(term="t")],
                                  **extra)
    if published:
        e["published_parsed"] = published.utctimetuple()
    return e


class TestEntryStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_keeps_fields(self):
        pub = NOW - timedelta(hours=3)
        e = entry("https://x/1", pub,
                  source=feedparser.FeedParserDict(href="https://outlet.example"))
        EntryStore(self.dir).add(FEED, [e], NOW)
        [rec] = EntryStore(self.dir).load().entries_for(FEED)
        [back] = merge_stored_entries([], [rec], NOW - timedelta(days=7))
        self.assertEqual(back.get("title"), "Title https://x/1")
        self.assertEqual(back.get("summary"), "s")
        self.assertEqual(back["source"].get("href"), "https://outlet.example")
        self.assertEqual([t.get("term") for t in back.get("tags", [])], ["t"])
        self.assertEqual(entry_datetime(back), pub)

    def test_each_entry_stored_once(self):
        store = EntryStore(self.dir)
        self.assertEqual(store.add(FEED, [entry("https://x/1"), entry("https://x/2")], NOW), 2)
        self.assertEqual(store.add(FEED, [entry("https://x/2"), entry("https://x/3")], NOW), 1)
        self.assertEqual(EntryStore(self.dir).load().add(FEED, [entry("https://x/1")], NOW), 0)
        self.assertEqual(len(EntryStore(self.dir).load().entries_for(FEED)), 3)

    def test_merge_prefers_live_and_adds_missing(self):
        start = NOW - timedelta(days=7)
        store = EntryStore(self.dir)
        store.add(FEED, [entry("https://x/old", NOW - timedelta(days=3)),
                         entry("https://x/both", NOW - timedelta(days=1))], NOW)
        live = [entry("https://x/both", NOW - timedelta(days=1)), entry("https://x/new", NOW)]
        merged = merge_stored_entries(live, store.entries_for(FEED), start)
        self.assertEqual([e.get("link") for e in merged],
                         ["https://x/both", "https://x/new", "https://x/old"])
        self.assertIs(merged[0], live[0])

    def test_undated_entry_only_merged_if_seen_in_window(self):
        store = EntryStore(self.dir)
        store.add(FEED, [entry("https://x/early")], NOW - timedelta(days=10))
        store.add(FEED, [entry("https://x/recent")], NOW - timedelta(days=2))
        merged = merge_stored_entries([], store.entries_for(FEED), NOW - timedelta(days=7))
        self.assertEqual([e.get("link") for e in merged], ["https://x/recent"])

    def test_read_only_store_saves_nothing(self):
        EntryStore(self.dir).add(FEED, [entry("https://x/1")], NOW)
        store = EntryStore(self.dir, read_only=True).load()
        self.assertEqual(store.add(FEED, [entry("https://x/2")], NOW), 0)
        self.assertEqual([e["link"] for e in EntryStore(self.dir).load().entries_for(FEED)],
                         ["https://x/1"])

    def test_prune_removes_old_days(self):
        store = EntryStore(self.dir, keep_days=35)
        store.add(FEED, [entry("https://x/old")], NOW - timedelta(days=40))
        store.add(FEED, [entry("https://x/new")], NOW)
        store.prune(NOW)
        self.assertEqual([e["link"] for e in EntryStore(self.dir).load().entries_for(FEED)],
                         ["https://x/new"])


class TestTextStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_survives_reload(self):
        TextStore(self.dir).save({"https://a/1": "Intel TDX text ü"}, NOW)
        self.assertEqual(TextStore(self.dir).load().get("https://a/1"), "Intel TDX text ü")
        self.assertIsNone(TextStore(self.dir).load().get("https://a/2"))

    def test_failures_are_retried_then_given_up(self):
        store = TextStore(self.dir)
        for i in range(TextStore.MAX_TRIES):
            self.assertTrue(store.needs_fetch("https://a/1"))
            store.save({"https://a/1": ""}, NOW + timedelta(hours=i))
        reloaded = TextStore(self.dir).load()
        self.assertFalse(reloaded.needs_fetch("https://a/1"))
        self.assertEqual(reloaded.get("https://a/1"), "")

    def test_later_success_replaces_failure(self):
        store = TextStore(self.dir)
        store.save({"https://a/1": ""}, NOW)
        store.save({"https://a/1": "text"}, NOW + timedelta(hours=1))
        self.assertEqual(TextStore(self.dir).load().get("https://a/1"), "text")

    def test_read_only_saves_nothing(self):
        TextStore(self.dir, read_only=True).save({"https://a/1": "x"}, NOW)
        self.assertIsNone(TextStore(self.dir).load().get("https://a/1"))

    def test_prune_removes_old_days(self):
        store = TextStore(self.dir, keep_days=14)
        store.save({"https://a/old": "x"}, NOW - timedelta(days=20))
        store.save({"https://a/new": "y"}, NOW)
        store.prune(NOW)
        reloaded = TextStore(self.dir).load()
        self.assertIsNone(reloaded.get("https://a/old"))
        self.assertEqual(reloaded.get("https://a/new"), "y")


class TestStoreArticleTexts(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.fetched = []

        def fake_fetch(urls, **kwargs):
            self.fetched.append(list(urls))
            return {u: f"text of {u}" for u in urls}
        self.real_fetch = crawler.fetch_article_texts
        crawler.fetch_article_texts = fake_fetch

    def tearDown(self):
        crawler.fetch_article_texts = self.real_fetch
        self.tmp.cleanup()

    def run_store(self, entries, now=NOW):
        args = argparse.Namespace(entry_store=self.dir, keywords="confidential computing,TDX")
        config = {"feeds": [{"url": FEED}]}
        store = EntryStore(self.dir).load()
        store.add(FEED, entries, now)
        return store_article_texts(args, config, store, now)

    def test_fetches_only_entries_without_a_title_match(self):
        matched = entry("https://a/match")
        matched["title"] = "Intel TDX news"
        self.assertEqual(self.run_store([matched, entry("https://a/other")]), (1, 0))
        self.assertEqual(self.fetched, [["https://a/other"]])
        texts = TextStore(text_store_dir(self.dir)).load()
        self.assertEqual(texts.get("https://a/other"), "text of https://a/other")

    def test_google_news_links_are_not_fetched(self):
        self.assertEqual(self.run_store([entry("https://news.google.com/rss/articles/x")]), (0, 0))

    def test_second_run_fetches_nothing_new(self):
        self.run_store([entry("https://a/1")])
        self.assertEqual(self.run_store([entry("https://a/1")], NOW + timedelta(hours=1)), (0, 0))

    def test_entries_first_seen_long_ago_are_skipped(self):
        store = EntryStore(self.dir)
        store.add(FEED, [entry("https://a/old")], NOW - timedelta(days=10))
        self.assertEqual(self.run_store([]), (0, 0))

    def test_old_articles_in_a_new_feed_are_skipped(self):
        self.assertEqual(self.run_store([entry("https://a/old", NOW - timedelta(days=30)),
                                         entry("https://a/new", NOW - timedelta(days=1))]), (1, 0))

    def test_backlog_is_capped_per_run(self):
        real_cap = crawler.TEXT_FETCHES_PER_STORE_RUN
        crawler.TEXT_FETCHES_PER_STORE_RUN = 2
        try:
            entries = [entry(f"https://a/{i}") for i in range(5)]
            self.assertEqual(self.run_store(entries), (2, 3))
            self.assertEqual(self.run_store([], NOW + timedelta(hours=1)), (2, 1))
        finally:
            crawler.TEXT_FETCHES_PER_STORE_RUN = real_cap


class TestFeedTimezone(unittest.TestCase):

    def parse(self, date_tag):
        xml = ('<rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>'
               f"<title>t</title>{date_tag}</item></channel></rss>")
        return feedparser.parse(xml).entries

    def test_zoneless_korean_time_becomes_utc(self):
        entries = self.parse("<pubDate>2026-10-29 21:48:48</pubDate>")
        localise_naive_dates(entries, "Asia/Seoul")
        self.assertEqual(entry_datetime(entries[0]),
                         datetime(2026, 10, 29, 12, 48, 48, tzinfo=timezone.utc))

    def test_dates_with_a_zone_are_left_alone(self):
        for tag, expected in [
            ("<pubDate>Thu, 29 Oct 2026 13:57:02 GMT</pubDate>",
             datetime(2026, 10, 29, 13, 57, 2, tzinfo=timezone.utc)),
            ("<pubDate>Thu, 29 Oct 2026 22:57:02 +0900</pubDate>",
             datetime(2026, 10, 29, 13, 57, 2, tzinfo=timezone.utc)),
            ("<dc:date>2026-10-29T08:00:00+08:00</dc:date>",
             datetime(2026, 10, 29, 0, 0, tzinfo=timezone.utc)),
        ]:
            entries = self.parse(tag)
            localise_naive_dates(entries, "Asia/Seoul")
            self.assertEqual(entry_datetime(entries[0]), expected, tag)


if __name__ == "__main__":
    unittest.main()
