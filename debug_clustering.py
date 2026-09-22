#!/usr/bin/env python3
"""Debug why L&T Vyoma articles aren't clustering together"""

import re
from datetime import datetime, timezone

def normalize_text(text):
    """Same normalization as in crawler.py"""
    if not text:
        return ""
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text.strip())
    return text

def clean_member_name(name):
    """Same function as in crawler.py"""
    if not name:
        return ""
    return normalize_text(name.lower().strip())

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

def _parse_pub_date(pub_str):
    """Same function as in crawler.py"""
    if not pub_str:
        return None
    try:
        import email.utils as _eu
        return _eu.parsedate_to_datetime(pub_str).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        return datetime.strptime(pub_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def infer_subject(title):
    """Simplified version of infer_subject"""
    # Look for key patterns in the title
    title_lower = title.lower()
    if 'l&t vyoma' in title_lower:
        return 'L&T Vyoma'
    if 'fortanix' in title_lower:
        return 'Fortanix'
    if 'ibm' in title_lower:
        return 'IBM'
    return ""

# Test L&T Vyoma articles from the output
lt_vyoma_articles = [
    {
        "title": "L&T Vyoma partners Fortanix to deliver sovereign AI security solutions in India - ETEnterpriseai.com",
        "published": "Wed, 08 Jul 2026 08:38:08 UTC",
        "url": "https://news.google.com/example1",
        "member": None
    },
    {
        "title": "L&T Vyoma partners with Fortanix to offer secure AI cloud solutions in India - Business Standard",
        "published": "Wed, 08 Jul 2026 07:46:59 UTC", 
        "url": "https://news.google.com/example2",
        "member": None
    },
    {
        "title": "L&T Vyoma partners with Fortanix for secure AI infrastructure - scanx.trade",
        "published": "Wed, 08 Jul 2026 07:33:03 UTC",
        "url": "https://news.google.com/example3", 
        "member": None
    },
    {
        "title": "L&T Vyoma forges strategic partnership with Fortanix Inc. - Business Standard",
        "published": "Wed, 08 Jul 2026 08:22:01 UTC",
        "url": "https://news.google.com/example4",
        "member": None
    },
    {
        "title": "L&T Vyoma, Fortanix partner on sovereign, secure AI services in India - Business Standard",
        "published": "Wed, 08 Jul 2026 10:18:28 UTC",
        "url": "https://news.google.com/example5",
        "member": None
    },
    {
        "title": "L&T Vyoma partners Fortanix for sovereign secure AI cloud services in India - Whalesbook",
        "published": "Wed, 08 Jul 2026 07:44:30 UTC",
        "url": "https://news.google.com/example6",
        "member": None
    }
]

print("=== L&T Vyoma Articles Clustering Debug ===\n")

# Analyze each article
for i, article in enumerate(lt_vyoma_articles):
    raw_co = article.get("member", "") or (infer_subject(article["title"]) or "")
    company = clean_member_name(raw_co) if raw_co else ""
    date = _parse_pub_date(article.get("published", ""))
    tokens = _title_tokens(article["title"])
    
    print(f"Article {i}:")
    print(f"  Title: {article['title']}")
    print(f"  Company: '{company}'")
    print(f"  Date: {date}")
    print(f"  Tokens: {sorted(tokens)}")
    print()

# Test clustering between first two articles
print("=== Pairwise Analysis (Article 0 vs 1) ===")
article1, article2 = lt_vyoma_articles[0], lt_vyoma_articles[1]

# Company check
raw_co1 = article1.get("member", "") or (infer_subject(article1["title"]) or "")
raw_co2 = article2.get("member", "") or (infer_subject(article2["title"]) or "")
company1 = clean_member_name(raw_co1) if raw_co1 else ""
company2 = clean_member_name(raw_co2) if raw_co2 else ""

print(f"Company1: '{company1}'")
print(f"Company2: '{company2}'")
print(f"Companies match: {company1 == company2}")
print()

# Date check
date1 = _parse_pub_date(article1.get("published", ""))
date2 = _parse_pub_date(article2.get("published", ""))
if date1 and date2:
    delta = abs((date1 - date2).total_seconds()) / 86400
    print(f"Date1: {date1}")
    print(f"Date2: {date2}")
    print(f"Days apart: {delta}")
    print(f"Within 1 day window: {delta <= 1}")
else:
    print("Date parsing failed")
print()

# Title similarity check
tokens1 = _title_tokens(article1["title"])
tokens2 = _title_tokens(article2["title"])
union_size = len(tokens1 | tokens2)
intersection_size = len(tokens1 & tokens2)
jaccard_similarity = intersection_size / union_size if union_size > 0 else 0

print(f"Tokens1: {sorted(tokens1)}")
print(f"Tokens2: {sorted(tokens2)}")
print(f"Intersection: {sorted(tokens1 & tokens2)}")
print(f"Union: {sorted(tokens1 | tokens2)}")
print(f"Jaccard similarity: {jaccard_similarity:.3f}")
print(f"Meets 0.7 threshold: {jaccard_similarity >= 0.7}")
print()

# URL domain check
from urllib.parse import urlparse
url1 = article1.get("url", "")
url2 = article2.get("url", "")
if url1 and url2:
    try:
        domain1 = urlparse(url1).netloc.lower()
        domain2 = urlparse(url2).netloc.lower()
        print(f"Domain1: {domain1}")
        print(f"Domain2: {domain2}")
        print(f"Same domain: {domain1 == domain2}")
        if domain1 != domain2:
            print(f"Different domains require 95% similarity: {jaccard_similarity >= 0.95}")
    except:
        print("URL parsing failed")

print(f"\n=== Would these cluster? ===")
would_cluster = (
    company1 and company2 and company1 == company2 and
    date1 and date2 and abs((date1 - date2).total_seconds()) / 86400 <= 1 and
    jaccard_similarity >= 0.7 and
    (domain1 == domain2 or jaccard_similarity >= 0.95)
)
print(f"Result: {would_cluster}")