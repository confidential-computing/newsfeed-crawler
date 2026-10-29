#!/usr/bin/env python3
"""
Unit tests for translating non-English titles in crawler.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler import _article_link, translate_titles


def translator(mapping):
    """translate stub: records the titles it was asked for."""
    def translate(titles):
        translate.asked.append(list(titles))
        return {t: mapping[t] for t in titles if t in mapping}
    translate.asked = []
    return translate


class TestTranslateTitles(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "translations.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_translates_non_english_and_keeps_original(self):
        articles = [
            {"title": "Microsoft amplía la computación confidencial", "lang": "es"},
            {"title": "Intel ships TDX update", "lang": "en"},
            {"title": "Old article with no lang"},
        ]
        t = translator({"Microsoft amplía la computación confidencial":
                        "Microsoft expands confidential computing"})
        self.assertEqual(translate_titles(articles, self.cache, t), 1)
        self.assertEqual(articles[0]["title"], "Microsoft expands confidential computing")
        self.assertEqual(articles[0]["title_original"], "Microsoft amplía la computación confidencial")
        self.assertNotIn("title_original", articles[1])
        self.assertNotIn("title_original", articles[2])
        self.assertEqual(t.asked, [["Microsoft amplía la computación confidencial"]])

    def test_cache_means_each_title_is_translated_once(self):
        t = translator({"Título": "Title"})
        translate_titles([{"title": "Título", "lang": "es"}], self.cache, t)
        again = [{"title": "Título", "lang": "es"}]
        translate_titles(again, self.cache, t)
        self.assertEqual(len(t.asked), 1)
        self.assertEqual(again[0]["title"], "Title")
        with open(self.cache) as f:
            self.assertEqual(json.load(f), {"Título": "Title"})

    def test_failure_keeps_original_title(self):
        def broken(titles):
            raise RuntimeError("claude not found")
        articles = [{"title": "Título", "lang": "pt"}]
        self.assertEqual(translate_titles(articles, self.cache, broken), 0)
        self.assertEqual(articles[0]["title"], "Título")
        self.assertNotIn("title_original", articles[0])

    def test_already_english_title_is_not_marked_translated(self):
        articles = [{"title": "Confidential Computing Summit", "lang": "es"}]
        translate_titles(articles, self.cache,
                         translator({"Confidential Computing Summit": "Confidential Computing Summit"}))
        self.assertNotIn("title_original", articles[0])


class TestArticleLink(unittest.TestCase):

    def test_translated_title_is_followed_by_original(self):
        a = {"title": "Microsoft expands confidential computing", "url": "https://x/1",
             "title_original": "Microsoft amplía la computación confidencial"}
        self.assertEqual(_article_link(a),
                         "[Microsoft expands confidential computing](https://x/1) "
                         "(original: Microsoft amplía la computación confidencial)")

    def test_english_title_is_a_plain_link(self):
        self.assertEqual(_article_link({"title": "T", "url": "https://x/1"}), "[T](https://x/1)")


if __name__ == "__main__":
    unittest.main()
