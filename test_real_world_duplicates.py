#!/usr/bin/env python3
"""
Test the deduplication functionality with realistic duplicate scenarios
that might occur in actual news crawling.
"""

import sys
import os

# Add the current directory to Python path to import crawler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crawler
from crawler import deduplicate_articles

# The test URLs are made up: never fetch them for the text comparison.
crawler.fetch_article_text = lambda url: ""

def test_real_world_scenario():
    """
    Test with realistic duplicate scenarios like the CC remote attestation case mentioned.
    """
    
    # Simulate the scenario mentioned where "CC remote attestation/trust mechanism flaw" 
    # appeared as duplicates from different URLs pointing to the same story
    articles = {
        "dont": [
            {
                "title": "Critical Remote Attestation Flaw Found in Confidential Computing Systems",
                "url": "https://securitynews.com/article/cc-attestation-flaw-2024?utm_source=twitter&utm_medium=social",
                "published": "Mon, 15 Jul 2024 10:00:00 GMT",
                "publisher": "Security News"
            },
            {
                "title": "Critical remote attestation flaw found in confidential computing systems",
                "url": "https://securitynews.com/article/cc-attestation-flaw-2024",  # Same URL minus tracking
                "published": "Mon, 15 Jul 2024 10:30:00 GMT",  
                "publisher": "Security News Syndicated"
            },
            {
                "title": "New Trust Mechanism Vulnerability Discovered in CC Remote Attestation",
                "url": "https://techblog.com/posts/trust-mechanism-vuln-cc?ref=homepage",
                "published": "Mon, 15 Jul 2024 11:00:00 GMT",
                "publisher": "Tech Blog"
            },
            {
                "title": "Researchers Find Major Security Hole in Intel SGX Attestation Process", 
                "url": "https://intel-watch.com/sgx-security-hole-discovered",
                "published": "Mon, 15 Jul 2024 12:00:00 GMT",
                "publisher": "Intel Watch"
            },
            {
                "title": "AMD SEV-SNP Also Affected by Remote Attestation Vulnerability",
                "url": "https://amd-news.com/sev-snp-remote-attestation-vuln",
                "published": "Tue, 16 Jul 2024 09:00:00 GMT", 
                "publisher": "AMD News"
            },
            {
                "title": "Critical Remote Attestation Flaw Found in Confidential Computing Systems - Updated",
                "url": "https://securitynews.com/article/cc-attestation-flaw-2024#updated",  # Same article with fragment
                "published": "Mon, 15 Jul 2024 15:00:00 GMT",
                "publisher": "Security News"
            }
        ],
        "by_member": [],
        "about_member": []
    }
    
    print("BEFORE DEDUPLICATION:")
    print(f"Total articles: {len(articles['dont'])}")
    for i, article in enumerate(articles['dont']):
        print(f"{i+1}. {article['title']} - {article['url']}")
    
    # Run deduplication
    result, duplicates_removed = deduplicate_articles(articles)
    
    print(f"\nAFTER DEDUPLICATION:")
    print(f"Duplicates removed: {duplicates_removed}")
    print(f"Remaining articles: {len(result['dont'])}")
    for i, article in enumerate(result['dont']):
        print(f"{i+1}. {article['title']} - {article['url']}")
    
    # Verify results
    print(f"\nEXPECTATIONS:")
    print("- Should detect URL duplicates between articles 1, 2, and 6 (same base URL)")
    print("- Articles 3, 4, 5 should remain as they're different stories")
    print("- Should remove 2-3 duplicates total")
    
    # Basic validation
    assert duplicates_removed >= 2, f"Expected to remove at least 2 duplicates, but removed {duplicates_removed}"
    assert len(result['dont']) >= 3, f"Expected at least 3 unique articles, but got {len(result['dont'])}"
    
    # Should have kept the first occurrence of the Security News article
    security_news_articles = [a for a in result['dont'] if 'securitynews.com' in a['url']]
    assert len(security_news_articles) == 1, f"Expected 1 Security News article after dedup, got {len(security_news_articles)}"
    
    print(f"\n✅ Test passed! Successfully deduplicated realistic scenarios.")
    return result


def test_edge_cases():
    """Test edge cases that might cause problems"""
    
    articles = {
        "dont": [
            {
                "title": "",  # Empty title
                "url": "https://example.com/empty-title",
                "published": "Mon, 01 Jan 2024 10:00:00 GMT",
                "publisher": "Example"
            },
            {
                "title": "Valid article with empty URL",
                "url": "",  # Empty URL
                "published": "Mon, 01 Jan 2024 11:00:00 GMT",
                "publisher": "Example"
            },
            {
                "title": "Article with malformed URL",
                "url": "not-a-valid-url",
                "published": "Mon, 01 Jan 2024 12:00:00 GMT",
                "publisher": "Example"
            },
            {
                "title": "Normal article",
                "url": "https://example.com/normal",
                "published": "Mon, 01 Jan 2024 13:00:00 GMT",
                "publisher": "Example"
            }
        ],
        "by_member": [],
        "about_member": []
    }
    
    print("\nTESTING EDGE CASES:")
    
    # This should not crash
    result, duplicates_removed = deduplicate_articles(articles)
    
    print(f"Edge case test completed without errors")
    print(f"Articles processed: {len(articles['dont'])} -> {len(result['dont'])}")
    print(f"Duplicates removed: {duplicates_removed}")
    
    # Should not have removed any articles since they're all different
    assert len(result['dont']) == 4, "Edge case articles should all be preserved"
    
    print("✅ Edge case test passed!")


def test_cross_category_deduplication():
    """Test that deduplication works across by_member, about_member, and dont categories"""
    
    articles = {
        "by_member": [
            {
                "title": "Intel Announces New SGX Security Features",
                "url": "https://intel.com/news/sgx-security-2024",
                "published": "Mon, 01 Jan 2024 10:00:00 GMT",
                "publisher": "Intel Blog",
                "member": "Intel Corporation"
            }
        ],
        "about_member": [
            {
                "title": "Intel announces new SGX security features",  # Very similar title
                "url": "https://techreporter.com/intel-sgx-security-announcement",
                "published": "Mon, 01 Jan 2024 11:00:00 GMT", 
                "publisher": "Tech Reporter",
                "member": "Intel Corporation"
            }
        ],
        "dont": [
            {
                "title": "Intel Announces New SGX Security Features - Analysis",
                "url": "https://analyst.com/intel-sgx-analysis",
                "published": "Mon, 01 Jan 2024 12:00:00 GMT",
                "publisher": "Security Analyst"
            }
        ]
    }
    
    print("\nTESTING CROSS-CATEGORY DEDUPLICATION:")
    print("Before:")
    print(f"  by_member: {len(articles['by_member'])} articles") 
    print(f"  about_member: {len(articles['about_member'])} articles")
    print(f"  dont: {len(articles['dont'])} articles")
    
    # Should have detected some cross-category duplicates
    total_before = sum(len(articles[cat]) for cat in articles)
    
    result, duplicates_removed = deduplicate_articles(articles)
    
    print("After:")
    print(f"  by_member: {len(result['by_member'])} articles")
    print(f"  about_member: {len(result['about_member'])} articles") 
    print(f"  dont: {len(result['dont'])} articles")
    print(f"  Duplicates removed: {duplicates_removed}")
    
    total_after = sum(len(result[cat]) for cat in result)
    
    print(f"Total articles: {total_before} -> {total_after}")
    print(f"Math check: {total_before} - {duplicates_removed} = {total_before - duplicates_removed}")
    
    # The same announcement written up by three different outlets is three
    # articles, not copies of one.
    assert duplicates_removed == 0, "Different outlets' reports of one story should all be kept"
    assert total_after == total_before - duplicates_removed, f"Math error: {total_after} != {total_before} - {duplicates_removed}"
    
    print("✅ Cross-category test passed: other outlets' reports kept!")


if __name__ == '__main__':
    test_real_world_scenario()
    test_edge_cases()
    test_cross_category_deduplication()
    print("\n🎉 All real-world deduplication tests passed!")