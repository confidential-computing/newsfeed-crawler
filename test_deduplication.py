#!/usr/bin/env python3
"""
Unit tests for the deduplication functionality in crawler.py
"""

import sys
import os
import unittest

# Add the current directory to Python path to import crawler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler import normalize_url, compute_content_hash, deduplicate_articles, _title_tokens


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
    
    def test_compute_content_hash(self):
        """Test content hashing for duplicate detection"""
        title1 = "Breaking: Major Security Flaw Found"
        title2 = "BREAKING: Major Security Flaw Found!!!"
        content = "This is the article content"
        
        hash1 = compute_content_hash(title1, content)
        hash2 = compute_content_hash(title2, content)
        
        # Similar titles with same content should produce same hash
        self.assertEqual(hash1, hash2)
        
        # Different content should produce different hash
        hash3 = compute_content_hash(title1, "Different content")
        self.assertNotEqual(hash1, hash3)
    
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
    
    def test_deduplicate_title_similarity(self):
        """Test deduplication based on title similarity"""
        articles = {
            "dont": [
                {
                    "title": "Major security vulnerability discovered in confidential computing",
                    "url": "https://site1.com/article1",
                    "published": "Mon, 01 Jan 2024 10:00:00 GMT",
                    "publisher": "Site 1"
                },
                {
                    "title": "Major Security Vulnerability Discovered in Confidential Computing",
                    "url": "https://site2.com/article2", 
                    "published": "Mon, 01 Jan 2024 11:00:00 GMT",
                    "publisher": "Site 2"
                },
                {
                    "title": "Completely different article about AI",
                    "url": "https://site3.com/article3",
                    "published": "Mon, 01 Jan 2024 12:00:00 GMT",
                    "publisher": "Site 3"
                }
            ],
            "by_member": [],
            "about_member": []
        }
        
        result, duplicates_removed = deduplicate_articles(articles)
        
        # Should detect the similar titles as duplicates
        self.assertEqual(duplicates_removed, 1)
        self.assertEqual(len(result["dont"]), 2)
        
        # Check that the AI article is preserved
        titles = [a["title"] for a in result["dont"]]
        self.assertTrue(any("AI" in title for title in titles))
    
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
        """Test that deduplication works across different categories"""
        articles = {
            "by_member": [
                {
                    "title": "Company announces new security feature",
                    "url": "https://company.com/news1",
                    "published": "Mon, 01 Jan 2024 10:00:00 GMT",
                    "publisher": "Company Blog",
                    "member": "Example Corp"
                }
            ],
            "about_member": [
                {
                    "title": "Company Announces New Security Feature", 
                    "url": "https://techreporter.com/news1",
                    "published": "Mon, 01 Jan 2024 11:00:00 GMT",
                    "publisher": "Tech Reporter",
                    "member": "Example Corp"
                }
            ],
            "dont": []
        }
        
        result, duplicates_removed = deduplicate_articles(articles)
        
        # Should detect duplicate across categories
        self.assertEqual(duplicates_removed, 1)
        
        # Should keep the first one (by_member)
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