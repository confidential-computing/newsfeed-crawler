#!/usr/bin/env python3
"""
Test to reproduce and fix the clustering issue where unrelated stories
are grouped under the same heading like "CC remote attestation/trust mechanism flaw"
"""

import sys
import os

# Add the current directory to Python path to import crawler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler import heuristic_cluster, infer_subject, _title_tokens, clean_member_name


def test_problematic_clustering():
    """
    Test case that reproduces the issue where unrelated CC stories
    get grouped under the same broad heading
    """
    print("🔍 TESTING PROBLEMATIC CLUSTERING SCENARIO\n")
    
    # Create articles that simulate the problem you described
    articles = [
        {
            "_id": 0,
            "title": "Critical remote attestation vulnerability discovered in Intel SGX",
            "url": "https://securitynews.com/sgx-attestation-vuln",
            "published": "Mon, 15 Jul 2024 09:00:00 GMT",
            "publisher": "Security News",
            "member": ""
        },
        {
            "_id": 1, 
            "title": "New trust mechanism flaw affects confidential computing platforms",
            "url": "https://techreporter.com/trust-mechanism-flaw",
            "published": "Mon, 15 Jul 2024 11:00:00 GMT",
            "publisher": "Tech Reporter", 
            "member": ""
        },
        {
            "_id": 2,
            "title": "AMD announces new confidential computing features for EPYC processors",
            "url": "https://amd.com/epyc-cc-features", 
            "published": "Tue, 16 Jul 2024 10:00:00 GMT",
            "publisher": "AMD",
            "member": ""
        },
        {
            "_id": 3,
            "title": "Microsoft releases confidential computing SDK for developers",
            "url": "https://microsoft.com/cc-sdk-release",
            "published": "Tue, 16 Jul 2024 14:00:00 GMT", 
            "publisher": "Microsoft",
            "member": ""
        },
        {
            "_id": 4,
            "title": "Google Cloud enhances confidential computing with new VM types",
            "url": "https://cloud.google.com/cc-vm-types",
            "published": "Wed, 17 Jul 2024 08:00:00 GMT",
            "publisher": "Google Cloud",
            "member": ""
        }
    ]
    
    print("ARTICLES TO CLUSTER:")
    for i, article in enumerate(articles):
        subject = infer_subject(article["title"])
        tokens = _title_tokens(article["title"])
        print(f"{i}. \"{article['title']}\"")
        print(f"   Inferred subject: {subject}")
        print(f"   Title tokens: {sorted(tokens)}")
        print()
    
    # Test current clustering behavior
    print("CURRENT CLUSTERING BEHAVIOR:")
    id_to_cluster, cluster_labels = heuristic_cluster(articles)
    
    # Group by cluster
    clusters = {}
    for article in articles:
        cluster_id = id_to_cluster[article["_id"]]
        if cluster_id not in clusters:
            clusters[cluster_id] = []
        clusters[cluster_id].append(article)
    
    for cluster_id, cluster_articles in clusters.items():
        label = cluster_labels[cluster_id]
        print(f"CLUSTER {cluster_id}: \"{label}\"")
        for article in cluster_articles:
            print(f"  - {article['title']}")
        print()
    
    # Analyze the problem
    print("ANALYSIS:")
    print(f"Total articles: {len(articles)}")
    print(f"Total clusters: {len(clusters)}")
    
    # Check if unrelated stories are being grouped together
    problematic_clusters = [cluster for cluster in clusters.values() if len(cluster) > 2]
    if problematic_clusters:
        print(f"❌ PROBLEM FOUND: {len(problematic_clusters)} clusters have >2 articles")
        for i, cluster in enumerate(problematic_clusters):
            print(f"   Problematic cluster {i+1} has {len(cluster)} articles:")
            for article in cluster:
                print(f"     - {article['title'][:80]}...")
            print()
    else:
        print("✅ No obvious over-clustering detected")
    
    return clusters


def test_clustering_thresholds():
    """Test different clustering parameters to find better values"""
    print("\n🔬 TESTING DIFFERENT CLUSTERING THRESHOLDS\n")
    
    # Sample articles that should NOT be clustered together
    test_articles = [
        {
            "_id": 0,
            "title": "Intel SGX remote attestation security flaw discovered by researchers", 
            "published": "Mon, 01 Jan 2024 10:00:00 GMT",
            "member": ""
        },
        {
            "_id": 1,
            "title": "AMD confidential computing roadmap announced at tech conference",
            "published": "Tue, 02 Jan 2024 10:00:00 GMT", 
            "member": ""
        },
        {
            "_id": 2,
            "title": "Microsoft confidential computing development tools released",
            "published": "Wed, 03 Jan 2024 10:00:00 GMT",
            "member": ""
        }
    ]
    
    # Test different Jaccard thresholds
    thresholds_to_test = [0.35, 0.5, 0.65, 0.8]
    
    for threshold in thresholds_to_test:
        print(f"Testing Jaccard threshold: {threshold}")
        id_to_cluster, cluster_labels = heuristic_cluster(test_articles, jaccard_threshold=threshold)
        
        clusters = {}
        for article in test_articles:
            cluster_id = id_to_cluster[article["_id"]]
            clusters.setdefault(cluster_id, []).append(article)
        
        print(f"  Result: {len(clusters)} clusters")
        if len(clusters) == len(test_articles):
            print("  ✅ All articles in separate clusters (good)")
        else:
            print("  ❌ Articles incorrectly grouped together")
            
        for cluster_id, cluster_articles in clusters.items():
            if len(cluster_articles) > 1:
                print(f"    Cluster {cluster_id}:")
                for article in cluster_articles:
                    print(f"      - {article['title'][:60]}...")
        print()
    
    # Test different date windows
    print("Testing date windows:")
    date_windows_to_test = [1, 3, 5, 7]
    
    for days in date_windows_to_test:
        print(f"Testing date window: {days} days")
        id_to_cluster, cluster_labels = heuristic_cluster(test_articles, date_window_days=days)
        clusters = {}
        for article in test_articles:
            cluster_id = id_to_cluster[article["_id"]]
            clusters.setdefault(cluster_id, []).append(article)
        print(f"  Result: {len(clusters)} clusters")
        print()


def analyze_subject_inference():
    """Analyze how subject inference might be causing over-broad clustering"""
    print("\n🎯 ANALYZING SUBJECT INFERENCE\n")
    
    test_titles = [
        "Critical remote attestation vulnerability discovered in Intel SGX",
        "New trust mechanism flaw affects confidential computing platforms", 
        "AMD announces new confidential computing features for EPYC processors",
        "Microsoft releases confidential computing SDK for developers",
        "Google Cloud enhances confidential computing with new VM types"
    ]
    
    print("SUBJECT INFERENCE ANALYSIS:")
    subjects = {}
    for title in test_titles:
        subject = infer_subject(title)
        clean_subject = clean_member_name(subject) if subject else ""
        
        print(f"Title: \"{title}\"")
        print(f"  Raw subject: {subject}")
        print(f"  Clean subject: {clean_subject}")
        
        if clean_subject:
            subjects.setdefault(clean_subject, []).append(title)
        print()
    
    print("SUBJECT GROUPINGS:")
    for subject, titles in subjects.items():
        print(f"Subject '{subject}': {len(titles)} articles")
        if len(titles) > 1:
            print("  ❌ POTENTIAL PROBLEM - Multiple articles with same subject:")
            for title in titles:
                print(f"    - {title}")
        print()


def main():
    """Run clustering analysis and propose fixes"""
    print("🔧 CC NEWS CRAWLER CLUSTERING ANALYSIS")
    print("=" * 50)
    
    # Test 1: Reproduce the clustering problem
    test_problematic_clustering()
    
    # Test 2: Test different thresholds
    test_clustering_thresholds()
    
    # Test 3: Analyze subject inference
    analyze_subject_inference()
    
    print("\n" + "=" * 50)
    print("RECOMMENDATIONS:")
    print("1. Increase Jaccard threshold from 0.35 to 0.6-0.7")
    print("2. Reduce date window from 5 days to 1-2 days")  
    print("3. Make subject inference more specific")
    print("4. Add additional checks to prevent over-clustering")


if __name__ == '__main__':
    main()