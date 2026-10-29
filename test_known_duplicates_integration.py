#!/usr/bin/env python3
"""
Integration test with known duplicates to verify the complete deduplication pipeline works.
This creates test articles that simulate real duplicate scenarios and validates the fix.
"""

import sys
import os
import tempfile
import json

# Add the current directory to Python path to import crawler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import crawler
from crawler import deduplicate_articles

# The test URLs are made up: never fetch them for the text comparison.
crawler.fetch_article_text = lambda url: ""


def simulate_duplicate_scenario():
    """
    Simulate the exact scenario mentioned: "CC remote attestation/trust mechanism flaw" 
    where two URLs pointed to the same story.
    """
    print("🔍 SIMULATING THE ORIGINAL DUPLICATE SCENARIO")
    print("Scenario: 'CC remote attestation/trust mechanism flaw' with duplicate URLs\n")
    
    # Create the exact type of duplicates that were problematic
    articles = {
        "dont": [
            # Original URL without tracking
            {
                "title": "Critical flaw discovered in CC remote attestation trust mechanism",
                "url": "https://securitytoday.com/articles/cc-attestation-vulnerability-2024",
                "published": "Mon, 15 Apr 2024 09:00:00 GMT",
                "publisher": "Security Today"
            },
            # Same URL with tracking parameters (common duplicate source)
            {
                "title": "Critical flaw discovered in CC remote attestation trust mechanism",
                "url": "https://securitytoday.com/articles/cc-attestation-vulnerability-2024?utm_source=newsletter&utm_medium=email&utm_campaign=security_weekly",
                "published": "Mon, 15 Apr 2024 09:30:00 GMT",
                "publisher": "Security Today Newsletter"
            },
            # Redirected/syndicated URL pointing to same content
            {
                "title": "Critical Flaw Discovered in CC Remote Attestation Trust Mechanism",
                "url": "https://news.google.com/articles/redirect?url=https%3A%2F%2Fsecuritytoday.com%2Farticles%2Fcc-attestation-vulnerability-2024",
                "published": "Mon, 15 Apr 2024 10:00:00 GMT",
                "publisher": "Google News",
                # The crawler records the outlet behind a Google News link
                "host": "securitytoday.com"
            },
            # Different URL, same story (picked up by different aggregator)
            {
                "title": "Researchers find critical flaw in confidential computing remote attestation trust mechanism",
                "url": "https://techwire.net/security/cc-remote-attestation-flaw-found",
                "published": "Mon, 15 Apr 2024 11:00:00 GMT",
                "publisher": "TechWire"
            },
            # Unrelated article to verify no false positives
            {
                "title": "Intel announces new processor architecture with enhanced security",
                "url": "https://intel.com/newsroom/processor-architecture-security",
                "published": "Tue, 16 Apr 2024 08:00:00 GMT",
                "publisher": "Intel Newsroom"
            }
        ],
        "by_member": [],
        "about_member": []
    }
    
    print("BEFORE DEDUPLICATION:")
    print(f"Total articles: {len(articles['dont'])}")
    for i, article in enumerate(articles['dont']):
        print(f"{i+1}. {article['title'][:80]}...")
        print(f"   URL: {article['url'][:100]}...")
        print(f"   Publisher: {article['publisher']}")
        print()
    
    # Run deduplication
    result, duplicates_removed = deduplicate_articles(articles)
    
    print("\nAFTER DEDUPLICATION:")
    print(f"Duplicates removed: {duplicates_removed}")
    print(f"Remaining articles: {len(result['dont'])}")
    for i, article in enumerate(result['dont']):
        print(f"{i+1}. {article['title'][:80]}...")
        print(f"   URL: {article['url'][:100]}...")
        print(f"   Publisher: {article['publisher']}")
        print()
    
    # Validation
    print("VALIDATION:")
    
    # Should remove at least 2-3 duplicates (the obvious URL variations)
    assert duplicates_removed >= 2, f"❌ Expected at least 2 duplicates removed, got {duplicates_removed}"
    print(f"✅ Removed {duplicates_removed} duplicates as expected")
    
    # Should keep the Intel article (not related to attestation flaw)
    intel_articles = [a for a in result['dont'] if 'intel' in a['url'].lower()]
    assert len(intel_articles) == 1, f"❌ Expected Intel article to be preserved"
    print("✅ Unrelated Intel article preserved (no false positive)")
    
    # Should keep at least 1 attestation article
    attestation_articles = [a for a in result['dont'] if 'attestation' in a['title'].lower()]
    assert len(attestation_articles) >= 1, f"❌ Expected at least 1 attestation article to remain"
    print("✅ Original attestation story preserved")
    
    print(f"\n🎉 ORIGINAL DUPLICATE SCENARIO FIXED!")
    print(f"The issue where 'CC remote attestation/trust mechanism flaw' appeared multiple times is now resolved.")
    
    return True


def test_performance_with_large_dataset():
    """Test performance with a larger dataset to ensure scaling"""
    import time
    
    print("\n⚡ PERFORMANCE TEST WITH LARGE DATASET")
    
    # Generate 500 articles with some duplicates mixed in
    articles = {"dont": [], "by_member": [], "about_member": []}
    
    base_titles = [
        "SGX vulnerability affects enterprise applications",
        "TDX technology provides hardware isolation", 
        "Confidential computing adoption grows in cloud",
        "Remote attestation protocols under security review",
        "New enclave technology promises better protection"
    ]
    
    base_urls = [
        "https://securitynews.com/articles/",
        "https://techtoday.com/news/",
        "https://cloudcomputing.org/posts/",
        "https://enterprise.tech/stories/",
        "https://infosec.daily/articles/"
    ]
    
    # Create mix of unique and duplicate articles
    for i in range(100):
        title = base_titles[i % len(base_titles)]
        base_url = base_urls[i % len(base_urls)]
        
        # Add some variation to make it interesting
        if i % 7 == 0:  # Create tracking URL duplicates
            url = f"{base_url}article-{i // 5}?utm_source=social&utm_campaign=test"
        elif i % 13 == 0:  # Create fragment duplicates  
            url = f"{base_url}article-{i // 5}#section{i % 3}"
        else:
            url = f"{base_url}article-{i}"
        
        articles["dont"].append({
            "title": f"{title} - Update {i // 10}" if i % 10 == 0 else title,
            "url": url,
            "published": f"Mon, {15 + (i % 15):02d} Apr 2024 {9 + (i % 12):02d}:00:00 GMT",
            "publisher": f"Publisher {i % 8}"
        })
    
    print(f"Generated {len(articles['dont'])} test articles")
    
    start_time = time.time()
    result, duplicates_removed = deduplicate_articles(articles)
    end_time = time.time()
    
    processing_time = (end_time - start_time) * 1000  # Convert to milliseconds
    
    print(f"Processing time: {processing_time:.1f}ms")
    print(f"Duplicates removed: {duplicates_removed}")
    print(f"Articles remaining: {len(result['dont'])}")
    print(f"Performance: {processing_time / len(articles['dont']):.2f}ms per article")
    
    # Verify performance is acceptable (should be under 10ms per article) 
    assert processing_time < 1000, f"❌ Performance too slow: {processing_time}ms for {len(articles['dont'])} articles"
    print("✅ Performance test passed")
    
    # Verify some duplicates were found
    assert duplicates_removed > 0, "❌ Should have found some duplicates in test data"
    print("✅ Duplicate detection working at scale")
    
    return True


def test_edge_case_robustness():
    """Test robustness with edge cases"""
    print("\n🛡️  EDGE CASE ROBUSTNESS TEST")
    
    edge_cases = {
        "dont": [
            # Empty/None values
            {"title": "", "url": "", "published": "", "publisher": ""},
            {"title": "Normal article", "url": None, "published": "Mon, 01 Jan 2024 10:00:00 GMT", "publisher": "Test"},
            
            # Unicode and special characters
            {"title": "Çødîfîçãtìøñ çômputîñg 🔒 security", "url": "https://test.com/ünîcødé", "published": "Mon, 01 Jan 2024 11:00:00 GMT", "publisher": "Unicode Test"},
            
            # Very long strings
            {"title": "A" * 1000, "url": "https://test.com/" + "b" * 500, "published": "Mon, 01 Jan 2024 12:00:00 GMT", "publisher": "Long Test"},
            
            # Malformed URLs
            {"title": "Article with bad URL", "url": "not-a-url-at-all", "published": "Mon, 01 Jan 2024 13:00:00 GMT", "publisher": "Bad URL Test"},
            {"title": "Article with space URL", "url": "http://test .com/space url", "published": "Mon, 01 Jan 2024 14:00:00 GMT", "publisher": "Space Test"},
            
            # Single character and very short
            {"title": "A", "url": "http://a.co", "published": "Mon, 01 Jan 2024 15:00:00 GMT", "publisher": "X"},
            
            # Same title, different content - should NOT be duplicates
            {"title": "Security Update", "url": "https://microsoft.com/security-update-1", "published": "Mon, 01 Jan 2024 16:00:00 GMT", "publisher": "Microsoft"},
            {"title": "Security Update", "url": "https://apple.com/security-update-2", "published": "Mon, 01 Jan 2024 17:00:00 GMT", "publisher": "Apple"},
        ],
        "by_member": [],
        "about_member": []
    }
    
    print(f"Testing {len(edge_cases['dont'])} edge case articles...")
    
    try:
        result, duplicates_removed = deduplicate_articles(edge_cases)
        print("✅ No crashes with edge cases")
        print(f"Articles processed: {len(edge_cases['dont'])} -> {len(result['dont'])}")
        print(f"Duplicates removed: {duplicates_removed}")
        
        # Should not have removed the different "Security Update" articles  
        security_updates = [a for a in result['dont'] if a.get('title') == 'Security Update']
        assert len(security_updates) == 2, "❌ False positive: different Security Update articles were merged"
        print("✅ No false positives on similar titles with different publishers")
        
        return True
        
    except Exception as e:
        print(f"❌ Edge case test failed: {e}")
        return False


def main():
    """Run comprehensive testing to validate the deduplication implementation"""
    print("🧪 COMPREHENSIVE DEDUPLICATION TESTING")
    print("=" * 50)
    
    tests_passed = 0
    total_tests = 3
    
    try:
        # Test 1: Original duplicate scenario
        if simulate_duplicate_scenario():
            tests_passed += 1
    except Exception as e:
        print(f"❌ Test 1 failed: {e}")
    
    try:
        # Test 2: Performance with large dataset  
        if test_performance_with_large_dataset():
            tests_passed += 1
    except Exception as e:
        print(f"❌ Test 2 failed: {e}")
    
    try:
        # Test 3: Edge case robustness
        if test_edge_case_robustness():
            tests_passed += 1
    except Exception as e:
        print(f"❌ Test 3 failed: {e}")
    
    print("\n" + "=" * 50)
    print(f"FINAL RESULTS: {tests_passed}/{total_tests} tests passed")
    
    if tests_passed == total_tests:
        print("🎉 ALL TESTS PASSED!")
        print("✅ The CC remote attestation duplicate issue has been FIXED")
        print("✅ Deduplication system is ready for production use")
        return True
    else:
        print(f"❌ {total_tests - tests_passed} tests failed")
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)