#!/usr/bin/env python3
"""
Unit tests for the deduplication functionality in crawler.py
"""

import sys
import os
import unittest

# Add the current directory to Python path to import crawler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler import (normalize_url, deduplicate_articles, _title_tokens,
                     text_overlap)

# Two texts long enough to judge (> DEDUP_MIN_SHINGLES phrases each).
STORY = ("Vendor X today announced a confidential computing service that runs AI "
         "models inside trusted execution environments on its cloud. " +
         " ".join(f"Paragraph {i} explains how customers attest workload {i} before "
                  f"sending sensitive data to the enclave." for i in range(10)))
OTHER_WRITEUP = ("Customers of Vendor X can now keep data encrypted while AI models use it, "
                 "the company said on Tuesday. " +
                 " ".join(f"Analyst {i} told us that point {i} matters for regulated "
                          f"industries such as banking and health care." for i in range(10)))


def texts(mapping):
    """fetch_text stub: URL -> text, recording which URLs were asked for."""
    def fetch(url):
        fetch.asked.append(url)
        return mapping.get(url, "")
    fetch.asked = []
    return fetch


class TestDeduplication(unittest.TestCase):
    
    def test_normalize_url(self):
        """Test URL normalization removes tracking parameters"""
        # Test tracking parameter removal
        url_with_tracking = "https://example.com/article?utm_source=google&utm_medium=email&id=123"
        normalized = normalize_url(url_with_tracking)
        self.assertEqual(normalized, "https://example.com/article?id=123")
        
        # Test case normalization
        mixed_case_url = "HTTPS://EXAMPLE.COM/Article"
        normalized = normalize_url(mixed_case_url)
        self.assertEqual(normalized, "https://example.com/article")
        
        # Test fragment removal
        url_with_fragment = "https://example.com/article#section1"
        normalized = normalize_url(url_with_fragment)
        self.assertEqual(normalized, "https://example.com/article")
        
        # Test multiple tracking params
        complex_url = "https://news.site.com/story?utm_campaign=spring&fbclid=abc123&gclid=xyz789&title=real-param"
        normalized = normalize_url(complex_url)
        self.assertEqual(normalized, "https://news.site.com/story?title=real-param")
    
    def test_deduplicate_exact_url_matches(self):
        """Test deduplication of articles with identical URLs"""
        articles = {
            "dont": [
                {
                    "title": "Article 1",
                    "url": "https://example.com/article1",
                    "published": "Mon, 01 Jan 2024 10:00:00 GMT",
                    "publisher": "Example News"
                },
                {
                    "title": "Article 1 (Duplicate URL)",
                    "url": "https://example.com/article1", 
                    "published": "Mon, 01 Jan 2024 11:00:00 GMT",
                    "publisher": "Another Publisher"
                },
                {
                    "title": "Different Article",
                    "url": "https://example.com/article2",
                    "published": "Mon, 01 Jan 2024 12:00:00 GMT", 
                    "publisher": "Example News"
                }
            ],
            "by_member": [],
            "about_member": []
        }
        
        result, duplicates_removed = deduplicate_articles(articles)
        
        self.assertEqual(duplicates_removed, 1)
        self.assertEqual(len(result["dont"]), 2)
        
        # Should keep the first one
        self.assertEqual(result["dont"][0]["title"], "Article 1")
        self.assertEqual(result["dont"][1]["title"], "Different Article")
    
    def test_deduplicate_url_normalization(self):
        """Test deduplication with URLs that normalize to the same thing"""
        articles = {
            "dont": [
                {
                    "title": "Article 1", 
                    "url": "https://example.com/article?id=123",
                    "published": "Mon, 01 Jan 2024 10:00:00 GMT",
                    "publisher": "Example News"
                },
                {
                    "title": "Article 1 (with tracking)",
                    "url": "https://example.com/article?utm_source=google&id=123&utm_medium=email",
                    "published": "Mon, 01 Jan 2024 11:00:00 GMT", 
                    "publisher": "Example News"
                }
            ],
            "by_member": [],
            "about_member": []
        }
        
        result, duplicates_removed = deduplicate_articles(articles)
        
        self.assertEqual(duplicates_removed, 1)
        self.assertEqual(len(result["dont"]), 1)
        self.assertEqual(result["dont"][0]["title"], "Article 1")
    
    def test_same_story_from_different_outlets_is_kept(self):
        """Similar titles from two outlets with their own write-ups: keep both"""
        articles = {
            "dont": [
                {"title": "Vendor X launches confidential AI service",
                 "url": "https://site1.com/a", "publisher": "Site 1"},
                {"title": "Vendor X Launches Confidential AI Service",
                 "url": "https://site2.com/b", "publisher": "Site 2"},
            ],
            "by_member": [], "about_member": [],
        }
        fetch = texts({"https://site1.com/a": STORY, "https://site2.com/b": OTHER_WRITEUP})
        result, removed = deduplicate_articles(articles, fetch_text=fetch)
        self.assertEqual(removed, 0)
        self.assertEqual(len(result["dont"]), 2)

    def test_syndicated_copy_is_removed(self):
        """Same text on two outlets (syndication): keep only the first"""
        articles = {
            "dont": [
                {"title": "Vendor X launches confidential AI service",
                 "url": "https://itbrief.asia/story/x", "publisher": "IT Brief Asia"},
                {"title": "Vendor X launches confidential AI service in Australia",
                 "url": "https://itbrief.com.au/story/x", "publisher": "IT Brief Australia"},
            ],
            "by_member": [], "about_member": [],
        }
        fetch = texts({"https://itbrief.asia/story/x": STORY,
                       "https://itbrief.com.au/story/x": STORY + " Local pricing follows."})
        result, removed = deduplicate_articles(articles, fetch_text=fetch)
        self.assertEqual(removed, 1)
        self.assertEqual([a["publisher"] for a in result["dont"]], ["IT Brief Asia"])

    def test_unreadable_text_keeps_both(self):
        """If either text can't be read, the articles are not judged copies"""
        articles = {
            "dont": [
                {"title": "Vendor X launches confidential AI service",
                 "url": "https://site1.com/a", "publisher": "Site 1"},
                {"title": "Vendor X launches confidential AI service",
                 "url": "https://site2.com/paywalled", "publisher": "Site 2"},
            ],
            "by_member": [], "about_member": [],
        }
        fetch = texts({"https://site1.com/a": STORY, "https://site2.com/paywalled": "Subscribe to read."})
        result, removed = deduplicate_articles(articles, fetch_text=fetch)
        self.assertEqual(removed, 0)

    def test_same_outlet_through_two_google_news_feeds(self):
        """One outlet's article reached via two Google News editions: one copy"""
        articles = {
            "dont": [
                {"title": "Vendor X launches confidential AI service - Example Times",
                 "url": "https://news.google.com/rss/articles/AAA", "host": "example.com",
                 "publisher": "Google News CC"},
                {"title": "Vendor X launches confidential AI service - Example Times",
                 "url": "https://news.google.com/rss/articles/BBB", "host": "example.com",
                 "publisher": "Google News CC - Australia"},
                {"title": "Vendor X launches confidential AI service - Other Daily",
                 "url": "https://news.google.com/rss/articles/CCC", "host": "other.com",
                 "publisher": "Google News CC"},
            ],
            "by_member": [], "about_member": [],
        }
        result, removed = deduplicate_articles(articles, fetch_text=texts({}))
        self.assertEqual(removed, 1)
        self.assertEqual([a["host"] for a in result["dont"]], ["example.com", "other.com"])

    def test_regional_editions_of_one_outlet(self):
        """ca.investing.com and in.investing.com are one outlet; .com.au is not a site"""
        articles = {
            "dont": [
                {"title": "Vendor X joins consortium - Investing.com Canada",
                 "url": "https://news.google.com/rss/articles/AAA", "host": "ca.investing.com"},
                {"title": "Vendor X joins consortium - Investing.com India",
                 "url": "https://news.google.com/rss/articles/BBB", "host": "in.investing.com"},
                {"title": "Vendor X joins consortium - iTnews",
                 "url": "https://news.google.com/rss/articles/CCC", "host": "www.itnews.com.au"},
                {"title": "Vendor X joins consortium - CRN Australia",
                 "url": "https://news.google.com/rss/articles/DDD", "host": "www.crn.com.au"},
            ],
            "by_member": [], "about_member": [],
        }
        result, removed = deduplicate_articles(articles, fetch_text=texts({}))
        self.assertEqual(removed, 1)
        self.assertEqual([a["host"] for a in result["dont"]],
                         ["ca.investing.com", "www.itnews.com.au", "www.crn.com.au"])

    def test_text_fetched_only_for_similar_titles(self):
        """Lazy: dissimilar titles never trigger a fetch"""
        articles = {
            "dont": [
                {"title": "Intel announces new SGX technology", "url": "https://a.com/1"},
                {"title": "AMD reveals new confidential computing features", "url": "https://b.com/2"},
            ],
            "by_member": [], "about_member": [],
        }
        fetch = texts({})
        deduplicate_articles(articles, fetch_text=fetch)
        self.assertEqual(fetch.asked, [])

    def test_text_overlap(self):
        self.assertGreater(text_overlap(STORY, STORY + " One more sentence here."), 0.9)
        self.assertLess(text_overlap(STORY, OTHER_WRITEUP), 0.2)
        self.assertEqual(text_overlap(STORY, "Too short."), 0.0)

    def test_deduplicate_no_false_positives(self):
        """Test that similar but distinct articles are not deduplicated"""
        articles = {
            "dont": [
                {
                    "title": "Intel announces new SGX technology",
                    "url": "https://intel-news.com/sgx1",
                    "published": "Mon, 01 Jan 2024 10:00:00 GMT",
                    "publisher": "Intel News"
                },
                {
                    "title": "AMD reveals new confidential computing features", 
                    "url": "https://amd-news.com/cc1",
                    "published": "Mon, 01 Jan 2024 11:00:00 GMT",
                    "publisher": "AMD News"
                },
                {
                    "title": "ARM introduces Confidential Compute Architecture",
                    "url": "https://arm-blog.com/cca1", 
                    "published": "Mon, 01 Jan 2024 12:00:00 GMT",
                    "publisher": "ARM Blog"
                }
            ],
            "by_member": [],
            "about_member": []
        }
        
        result, duplicates_removed = deduplicate_articles(articles)
        
        # These should all be considered distinct articles
        self.assertEqual(duplicates_removed, 0)
        self.assertEqual(len(result["dont"]), 3)
    
    def test_deduplicate_across_categories(self):
        """A copy in a later category is removed; the first category keeps it"""
        articles = {
            "by_member": [
                {"title": "Company announces new security feature",
                 "url": "https://company.com/news1", "publisher": "Company Blog",
                 "member": "Example Corp"},
            ],
            "about_member": [
                {"title": "Company Announces New Security Feature",
                 "url": "https://techreporter.com/news1", "publisher": "Tech Reporter",
                 "member": "Example Corp"},
            ],
            "dont": [],
        }
        fetch = texts({"https://company.com/news1": STORY, "https://techreporter.com/news1": STORY})
        result, removed = deduplicate_articles(articles, fetch_text=fetch)
        self.assertEqual(removed, 1)
        self.assertEqual(len(result["by_member"]), 1)
        self.assertEqual(len(result["about_member"]), 0)


class TestTitleTokens(unittest.TestCase):
    """Test the _title_tokens function used for similarity detection"""
    
    def test_title_tokens(self):
        title = "Breaking: Major Security Vulnerability Found in Intel SGX"
        tokens = _title_tokens(title)
        
        # Should normalize to lowercase and split on word boundaries
        expected_words = {"breaking", "major", "security", "vulnerability", "found", "intel", "sgx"}
        self.assertEqual(tokens, expected_words)
    
    def test_title_tokens_punctuation(self):
        title = "Article!@# with... lots*** of punctuation???"
        tokens = _title_tokens(title)
        
        # Note: _title_tokens removes stop words like "with" and "of"
        expected_words = {"article", "lots", "punctuation"}
        self.assertEqual(tokens, expected_words)


if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)