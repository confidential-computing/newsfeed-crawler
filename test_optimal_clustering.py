#!/usr/bin/env python3
"""Test different Jaccard thresholds to find optimal clustering"""

import re
from datetime import datetime, timezone
import email.utils as _eu

def _title_tokens(title):
    """Same function as in crawler.py"""
    _stop = {
        'the', 'a', 'an', 'in', 'on', 'at', 'to', 'of', 'for', 'and', 'or',
        'is', 'are', 'was', 'were', 'it', 'its', 'with', 'by', 'as', 'from',
        'that', 'this', 'be', 'has', 'have',
    }
    return {
        w for w in re.sub(r"[^\w\s]", "", title.lower()).split()
        if w not in _stop and len(w) > 1
    }

def jaccard_similarity(title1, title2):
    """Calculate Jaccard similarity between two titles"""
    tokens1 = _title_tokens(title1)
    tokens2 = _title_tokens(title2)
    union_size = len(tokens1 | tokens2)
    if union_size == 0:
        return 0.0
    return len(tokens1 & tokens2) / union_size

# Test cases: SHOULD cluster (same story)
same_story_pairs = [
    (
        "L&T Vyoma partners Fortanix to deliver sovereign AI security solutions in India - ETEnterpriseai.com",
        "L&T Vyoma partners with Fortanix to offer secure AI cloud solutions in India - Business Standard"
    ),
    (
        "L&T Vyoma partners with Fortanix for secure AI infrastructure - scanx.trade", 
        "L&T Vyoma forges strategic partnership with Fortanix Inc. - Business Standard"
    ),
    (
        "IBM Launches Compact z17 and LinuxONE Systems to Address Data Center Space and Cost Constraints - StorageNewsletter",
        "IBM to announce second-quarter 2026 financial results on July 22 - scanx.trade"
    )
]

# Test cases: should NOT cluster (different stories)
different_story_pairs = [
    (
        "L&T Vyoma partners Fortanix to deliver sovereign AI security solutions in India",
        "Can IBM's Enterprise Infrastructure Portfolio Expansion Aid Growth?"
    ),
    (
        "L&T Vyoma partners with Fortanix for secure AI infrastructure",
        "Secret Network Unveils Proposal to Move SCRT to Arbitrum"
    ),
    (
        "NVIDIA Corporation announces new GPU architecture",
        "Microsoft invests in quantum computing research" 
    )
]

print("=== JACCARD SIMILARITY ANALYSIS ===\n")

print("SHOULD CLUSTER (Same Story):")
print("-" * 40)
same_story_similarities = []
for title1, title2 in same_story_pairs:
    similarity = jaccard_similarity(title1, title2)
    same_story_similarities.append(similarity)
    print(f"Similarity: {similarity:.3f}")
    print(f"Title 1: {title1}")
    print(f"Title 2: {title2}")
    print()

print("SHOULD NOT CLUSTER (Different Stories):")
print("-" * 45)
different_story_similarities = []
for title1, title2 in different_story_pairs:
    similarity = jaccard_similarity(title1, title2)
    different_story_similarities.append(similarity)
    print(f"Similarity: {similarity:.3f}")
    print(f"Title 1: {title1}")
    print(f"Title 2: {title2}")
    print()

# Analyze optimal threshold
print("=== THRESHOLD ANALYSIS ===")
print(f"Same story similarities: {[f'{s:.3f}' for s in same_story_similarities]}")
print(f"Different story similarities: {[f'{s:.3f}' for s in different_story_similarities]}")

if same_story_similarities and different_story_similarities:
    max_different = max(different_story_similarities)
    min_same = min(same_story_similarities)
    
    print(f"\nMax similarity for DIFFERENT stories: {max_different:.3f}")
    print(f"Min similarity for SAME stories: {min_same:.3f}")
    
    if min_same > max_different:
        optimal_threshold = (min_same + max_different) / 2
        print(f"✅ Clear separation exists!")
        print(f"Suggested threshold: {optimal_threshold:.3f}")
    else:
        print(f"❌ Overlap detected - need more nuanced approach")
        print(f"Current threshold 0.7 would:")
        same_clustered = sum(1 for s in same_story_similarities if s >= 0.7)
        different_clustered = sum(1 for s in different_story_similarities if s >= 0.7)
        print(f"  - Cluster {same_clustered}/{len(same_story_similarities)} same stories")
        print(f"  - Wrongly cluster {different_clustered}/{len(different_story_similarities)} different stories")

# Test various thresholds
print(f"\n=== THRESHOLD TESTING ===")
thresholds = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
for threshold in thresholds:
    same_clustered = sum(1 for s in same_story_similarities if s >= threshold)
    different_clustered = sum(1 for s in different_story_similarities if s >= threshold) 
    print(f"Threshold {threshold}: Same={same_clustered}/{len(same_story_similarities)}, Different={different_clustered}/{len(different_story_similarities)}")