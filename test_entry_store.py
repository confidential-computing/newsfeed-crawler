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

from crawler import EntryStore, entry_datetime, merge_stored_entries

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


if __name__ == "__main__":
    unittest.main()
