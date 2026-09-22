#!/usr/bin/env python3
"""
Test that reproduces the actual clustering problem where multiple unrelated 
CC/attestation stories get grouped under one heading.
"""

import sys
import os

# Add the current directory to Python path to import crawler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler import heuristic_cluster, infer_subject, _title_tokens


def test_real_attestation_clustering_problem():
    """
    Reproduce the exact issue: multiple different CC/attestation stories
    getting grouped under "CC remote attestation/trust mechanism flaw"
    """
    print("🔍 REPRODUCING REAL CC ATTESTATION CLUSTERING PROBLEM\n")
    
    # Create articles that SHOULD be grouped separately but might get clustered together
    # These represent different CC security stories that might share common keywords
    articles = [
        {
            "_id": 0,
            "title": "Critical remote attestation vulnerability found in Intel SGX implementation",
            "url": "https://securityresearch.com/sgx-attestation-vuln-2024",
            "published": "Mon, 15 Apr 2024 09:00:00 GMT",
            "publisher": "Security Research",
            "member": ""
        },
        {
            "_id": 1, 
            "title": "Remote attestation trust mechanism bypass discovered in confidential VMs",
            "url": "https://cloudnews.com/vm-attestation-bypass",
            "published": "Mon, 15 Apr 2024 11:00:00 GMT",
            "publisher": "Cloud News",
            "member": ""
        },
        {
            "_id": 2,
            "title": "New trust verification flaw affects remote attestation in AMD SEV",
            "url": "https://amdwatch.com/sev-trust-verification-flaw",
            "published": "Tue, 16 Apr 2024 08:00:00 GMT",
            "publisher": "AMD Watch",
            "member": ""
        },
        {
            "_id": 3,
            "title": "Confidential computing trust mechanisms vulnerable to side-channel attacks",
            "url": "https://techsecurity.com/cc-trust-sidechannel",
            "published": "Tue, 16 Apr 2024 14:00:00 GMT",
            "publisher": "Tech Security",
            "member": ""
        },
        {
            "_id": 4,
            "title": "Remote attestation protocol weakness enables privilege escalation",
            "url": "https://infosectoday.com/attestation-privesc",
            "published": "Wed, 17 Apr 2024 10:00:00 GMT",
            "publisher": "InfoSec Today", 
            "member": ""
        },
        {
            "_id": 5,
            "title": "Trust anchor compromise affects confidential computing attestation chains",
            "url": "https://enterprisesec.com/trust-anchor-compromise",
            "published": "Wed, 17 Apr 2024 16:00:00 GMT",
            "publisher": "Enterprise Security",
            "member": ""
        }
    ]
    
    print("TEST ARTICLES (each should be a SEPARATE story):")
    for i, article in enumerate(articles):
        subject = infer_subject(article["title"])
        tokens = _title_tokens(article["title"])
        print(f"{i}. \"{article['title']}\"")
        print(f"   Subject: '{subject}'")
        print(f"   Key tokens: {sorted(list(tokens))}")
        
        # Check overlap with other articles
        for j, other in enumerate(articles[i+1:], i+1):
            other_tokens = _title_tokens(other["title"])
            overlap = tokens & other_tokens
            jaccard = len(overlap) / len(tokens | other_tokens) if (tokens | other_tokens) else 0
            if jaccard >= 0.35:  # Current threshold
                print(f"   ❌ HIGH OVERLAP with article {j}: {jaccard:.2f} (tokens: {sorted(list(overlap))})")
        print()
    
    # Test current clustering
    print("CURRENT HEURISTIC CLUSTERING:")
    id_to_cluster, cluster_labels = heuristic_cluster(articles, jaccard_threshold=0.35, date_window_days=5)
    
    # Group articles by cluster
    clusters = {}
    for article in articles:
        cluster_id = id_to_cluster[article["_id"]]
        clusters.setdefault(cluster_id, []).append(article)
    
    problem_found = False
    for cluster_id, cluster_articles in clusters.items():
        label = cluster_labels[cluster_id]
        print(f"\nCLUSTER {cluster_id}: \"{label}\"")
        print(f"Articles in cluster: {len(cluster_articles)}")
        
        if len(cluster_articles) > 1:
            print(f"❌ PROBLEM: {len(cluster_articles)} different stories grouped together!")
            problem_found = True
            
        for article in cluster_articles:
            print(f"  - {article['title']}")
    
    if problem_found:
        print(f"\n❌ CLUSTERING PROBLEM CONFIRMED!")
        print(f"   {len(articles)} different CC security stories → {len(clusters)} clusters")
        print(f"   Some unrelated stories are being grouped together")
    else:
        print(f"\n✅ No clustering problem with this test case")
        print(f"   {len(articles)} stories → {len(clusters)} clusters (good separation)")
    
    return clusters, problem_found


def test_with_more_conservative_settings():
    """Test with more conservative clustering settings"""
    print("\n🔧 TESTING MORE CONSERVATIVE CLUSTERING SETTINGS\n")
    
    # Same test articles as above
    articles = [
        {
            "_id": 0,
            "title": "Critical remote attestation vulnerability found in Intel SGX implementation",
            "published": "Mon, 15 Apr 2024 09:00:00 GMT",
            "member": ""
        },
        {
            "_id": 1, 
            "title": "Remote attestation trust mechanism bypass discovered in confidential VMs",
            "published": "Mon, 15 Apr 2024 11:00:00 GMT",
            "member": ""
        },
        {
            "_id": 2,
            "title": "New trust verification flaw affects remote attestation in AMD SEV",
            "published": "Tue, 16 Apr 2024 08:00:00 GMT",
            "member": ""
        }
    ]
    
    # Test different combinations of conservative settings
    test_configs = [
        {"jaccard_threshold": 0.35, "date_window_days": 5, "name": "Current (aggressive)"},
        {"jaccard_threshold": 0.6, "date_window_days": 3, "name": "Moderate"},
        {"jaccard_threshold": 0.75, "date_window_days": 1, "name": "Conservative"},
        {"jaccard_threshold": 0.85, "date_window_days": 1, "name": "Very conservative"}
    ]
    
    for config in test_configs:
        print(f"Testing: {config['name']}")
        print(f"  Jaccard threshold: {config['jaccard_threshold']}")
        print(f"  Date window: {config['date_window_days']} days")
        
        id_to_cluster, cluster_labels = heuristic_cluster(
            articles, 
            jaccard_threshold=config['jaccard_threshold'], 
            date_window_days=config['date_window_days']
        )
        
        clusters = {}
        for article in articles:
            cluster_id = id_to_cluster[article["_id"]]
            clusters.setdefault(cluster_id, []).append(article)
        
        print(f"  Result: {len(clusters)} clusters")
        if len(clusters) == len(articles):
            print("  ✅ Perfect separation (each article in own cluster)")
        else:
            print("  ❌ Some articles still grouped together")
            for cluster_id, cluster_articles in clusters.items():
                if len(cluster_articles) > 1:
                    print(f"    Cluster {cluster_id}: {len(cluster_articles)} articles grouped")
        print()


def test_ai_clustering_prompt_improvement():
    """Test improving the AI clustering prompt to be more conservative"""
    print("\n🤖 IMPROVED AI CLUSTERING PROMPT\n")
    
    current_prompt = """You are a news editor. Given a JSON array of news article metadata, group them 
into clusters where each cluster covers exactly one distinct news story or event. 
Articles from different outlets covering the same announcement, release, or event 
should be in the same cluster. Articles covering different topics must be in 
different clusters."""
    
    improved_prompt = """You are a news editor. Given a JSON array of news article metadata, group them 
into clusters where each cluster covers exactly one distinct, specific news story or event.

STRICT CLUSTERING RULES:
- Only group articles if they cover the EXACT SAME specific incident, announcement, or event
- Different vulnerabilities, even in similar technologies, should be SEPARATE clusters
- Different company announcements should be SEPARATE clusters 
- General topics (like "confidential computing news") should NOT be grouped together
- When in doubt, keep articles in separate clusters
- Each cluster should represent one specific, factual event or announcement

Articles covering related but distinct topics MUST be in different clusters."""
    
    print("CURRENT AI PROMPT:")
    print(current_prompt)
    print(f"\nCurrent prompt length: {len(current_prompt)} characters")
    
    print("\nIMPROVED AI PROMPT:")
    print(improved_prompt)
    print(f"\nImproved prompt length: {len(improved_prompt)} characters")
    
    print("\nKey improvements:")
    print("✅ Added STRICT CLUSTERING RULES section")
    print("✅ Emphasized 'EXACT SAME specific incident'")
    print("✅ Explicitly forbids grouping different vulnerabilities")
    print("✅ Added 'when in doubt, separate' guidance")
    print("✅ Emphasized specific factual events over general topics")
    
    return improved_prompt


def main():
    """Run comprehensive clustering problem analysis and fixes"""
    print("🚨 CC NEWS CRAWLER CLUSTERING PROBLEM ANALYSIS")
    print("=" * 60)
    
    # Test 1: Try to reproduce the actual problem
    clusters, problem_found = test_real_attestation_clustering_problem()
    
    # Test 2: Test more conservative settings
    test_with_more_conservative_settings()
    
    # Test 3: Improve AI clustering prompt
    improved_prompt = test_ai_clustering_prompt_improvement()
    
    print("\n" + "=" * 60)
    print("🔧 RECOMMENDED FIXES:")
    print()
    
    if problem_found:
        print("❌ CLUSTERING PROBLEM CONFIRMED - Fixes needed:")
    else:
        print("✅ No major clustering problems found, but preventive improvements recommended:")
    
    print("\n1. HEURISTIC CLUSTERING IMPROVEMENTS:")
    print("   - Increase Jaccard threshold: 0.35 → 0.6 or 0.7")
    print("   - Reduce date window: 5 days → 2 days")  
    print("   - Add domain-specific logic for CC terms")
    
    print("\n2. AI CLUSTERING IMPROVEMENTS:")
    print("   - Use improved prompt with stricter rules")
    print("   - Add examples of what NOT to cluster together")
    
    print("\n3. ADDITIONAL SAFEGUARDS:")
    print("   - Add manual verification mode")
    print("   - Implement cluster quality metrics")
    print("   - Add post-clustering validation")
    
    return problem_found


if __name__ == '__main__':
    main()