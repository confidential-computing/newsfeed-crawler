#!/usr/bin/env python3
"""
Fix clustering issues in the CC News Crawler.
Implements conservative clustering improvements and diagnostic tools.
"""

import sys
import os
import json

# Add the current directory to Python path to import crawler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawler import heuristic_cluster, infer_subject, _title_tokens


def improved_heuristic_cluster(articles, date_window_days=2, jaccard_threshold=0.7, require_same_domain=True):
    """
    Improved heuristic clustering that's more conservative to prevent
    over-clustering of unrelated stories.
    
    Changes from original:
    - Higher Jaccard threshold (0.7 vs 0.35)
    - Shorter date window (2 days vs 5 days)  
    - Optional domain checking to prevent cross-domain clustering
    - More conservative subject matching
    """
    n = len(articles)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    # Extract metadata for each article
    companies = []
    dates = []
    tokens = []
    urls = []
    
    for a in articles:
        # Subject inference
        raw_co = a.get("member", "") or (infer_subject(a["title"]) or "")
        companies.append(raw_co.lower() if raw_co else "")
        
        # Date parsing
        from crawler import _parse_pub_date
        dates.append(_parse_pub_date(a.get("published", "")))
        
        # Title tokens
        tokens.append(_title_tokens(a["title"]))
        
        # URL domain extraction
        try:
            from urllib.parse import urlparse
            domain = urlparse(a.get("url", "")).netloc.lower()
            urls.append(domain)
        except:
            urls.append("")

    # More conservative clustering logic
    for i in range(n):
        if not companies[i]:  # Skip articles without clear subject
            continue
            
        for j in range(i + 1, n):
            # Must have same company/subject
            if companies[i] != companies[j]:
                continue
                
            # Must be within date window
            if dates[i] and dates[j]:
                delta = abs((dates[i] - dates[j]).total_seconds()) / 86400
                if delta > date_window_days:
                    continue
            
            # Title similarity check with higher threshold
            t_i, t_j = tokens[i], tokens[j]
            union_size = len(t_i | t_j)
            if union_size == 0:
                continue
                
            jaccard = len(t_i & t_j) / union_size
            if jaccard < jaccard_threshold:
                continue
            
            # Optional: prevent clustering across different domains
            # (articles from different news sites are more likely to be different stories)
            if require_same_domain and urls[i] and urls[j] and urls[i] != urls[j]:
                # Allow clustering across domains only with very high similarity
                if jaccard < 0.85:
                    continue
            
            # All checks passed - cluster these articles
            union(i, j)

    # Generate clusters
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    id_to_cluster = {}
    cluster_labels = {}
    
    for cid, indices in enumerate(groups.values()):
        # More specific labeling
        if len(indices) == 1:
            # Single article - use title as label
            idx = indices[0]
            label = articles[idx]["title"][:80]
        else:
            # Multiple articles - find common theme
            all_tokens = set()
            for idx in indices:
                all_tokens.update(tokens[idx])
            
            # Use most common meaningful tokens
            token_counts = {}
            for idx in indices:
                for token in tokens[idx]:
                    if len(token) > 3:  # Ignore short words
                        token_counts[token] = token_counts.get(token, 0) + 1
            
            # Build label from most common significant tokens
            common_tokens = sorted(token_counts.items(), key=lambda x: x[1], reverse=True)[:4]
            if common_tokens:
                label = " ".join([token for token, count in common_tokens if count > 1]).title()
            else:
                label = companies[indices[0]].title() if companies[indices[0]] else f"Story {cid + 1}"
        
        cluster_labels[cid] = label
        for idx in indices:
            id_to_cluster[articles[idx]["_id"]] = cid

    return id_to_cluster, cluster_labels


def diagnose_clustering_problems(articles, id_to_cluster, cluster_labels):
    """
    Analyze clustering results to identify potential problems.
    """
    print("🔍 CLUSTERING DIAGNOSIS")
    print("=" * 50)
    
    # Group articles by cluster
    clusters = {}
    for article in articles:
        cluster_id = id_to_cluster[article["_id"]]
        clusters.setdefault(cluster_id, []).append(article)
    
    print(f"Total articles: {len(articles)}")
    print(f"Total clusters: {len(clusters)}")
    print(f"Average articles per cluster: {len(articles)/len(clusters):.2f}")
    print()
    
    # Identify potentially problematic clusters
    large_clusters = [(cid, cluster) for cid, cluster in clusters.items() if len(cluster) > 3]
    diverse_clusters = []
    
    for cluster_id, cluster_articles in clusters.items():
        if len(cluster_articles) <= 1:
            continue
            
        # Check for diversity within cluster (different publishers, domains)
        publishers = set(a.get("publisher", "") for a in cluster_articles)
        domains = set()
        for a in cluster_articles:
            try:
                from urllib.parse import urlparse
                domain = urlparse(a.get("url", "")).netloc
                domains.add(domain)
            except:
                pass
        
        if len(publishers) > 2 or len(domains) > 2:
            diverse_clusters.append((cluster_id, cluster_articles, publishers, domains))
    
    # Report potential problems
    if large_clusters:
        print("⚠️  LARGE CLUSTERS (>3 articles):")
        for cluster_id, cluster_articles in large_clusters:
            label = cluster_labels[cluster_id]
            print(f"  Cluster {cluster_id}: '{label}' ({len(cluster_articles)} articles)")
            for article in cluster_articles:
                print(f"    - {article['title'][:60]}...")
            print()
    
    if diverse_clusters:
        print("⚠️  DIVERSE CLUSTERS (multiple publishers/domains):")
        for cluster_id, cluster_articles, publishers, domains in diverse_clusters:
            label = cluster_labels[cluster_id]
            print(f"  Cluster {cluster_id}: '{label}'")
            print(f"    Publishers: {list(publishers)[:3]}")
            print(f"    Domains: {list(domains)[:3]}")
            for article in cluster_articles:
                print(f"    - {article['title'][:50]}... ({article.get('publisher', '')})")
            print()
    
    if not large_clusters and not diverse_clusters:
        print("✅ No obvious clustering problems detected")
    
    return large_clusters, diverse_clusters


def improved_ai_clustering_prompt():
    """Generate improved AI clustering prompt with stricter rules"""
    return """You are a news editor. Given JSON article metadata, group them into clusters where each cluster covers exactly ONE specific, distinct news story or event.

STRICT CLUSTERING RULES:
- Only group articles covering the EXACT SAME specific incident, announcement, or event
- Different vulnerabilities/flaws, even in similar technologies, MUST be separate clusters
- Different company announcements MUST be separate clusters
- General topics like "confidential computing news" should NOT be clustered together
- Articles about related but distinct events MUST be in different clusters
- When in doubt, keep articles SEPARATE

EXAMPLES OF WHAT NOT TO CLUSTER:
- "Intel SGX vulnerability" + "AMD SEV vulnerability" → SEPARATE (different flaws)
- "Microsoft AI announcement" + "Google AI announcement" → SEPARATE (different companies)
- "Remote attestation flaw A" + "Remote attestation flaw B" → SEPARATE (different flaws)

Each cluster should represent one specific factual event, not a general topic.

Respond with ONLY JSON: {"clusters": [{"label": "Specific event description", "ids": [1, 2]}, ...]]}

Articles: {articles_json}"""


def apply_clustering_fixes():
    """Apply fixes to the main crawler.py file"""
    print("🔧 APPLYING CLUSTERING FIXES")
    print("=" * 50)
    
    fixes_applied = []
    
    # 1. Update heuristic clustering parameters
    print("1. Updating heuristic clustering parameters...")
    
    try:
        with open('crawler.py', 'r') as f:
            content = f.read()
        
        # Update default parameters to be more conservative
        old_line = "def heuristic_cluster(articles, date_window_days=5, jaccard_threshold=0.35):"
        new_line = "def heuristic_cluster(articles, date_window_days=2, jaccard_threshold=0.6):"
        
        if old_line in content:
            content = content.replace(old_line, new_line)
            fixes_applied.append("Updated heuristic clustering parameters: date_window_days=5→2, jaccard_threshold=0.35→0.6")
        
        # 2. Update AI clustering prompt
        print("2. Updating AI clustering prompt...")
        
        # Find and replace the clustering prompt
        old_prompt_start = '_CLUSTER_PROMPT_TPL = ('
        if old_prompt_start in content:
            start_idx = content.index(old_prompt_start)
            # Find the end of the prompt (next line starting with ')')
            lines = content[start_idx:].split('\n')
            end_idx = start_idx
            for i, line in enumerate(lines):
                if line.strip() == ')':
                    end_idx = start_idx + content[start_idx:].index('\n'.join(lines[:i+1])) + len('\n'.join(lines[:i+1]))
                    break
            
            new_prompt = f'''_CLUSTER_PROMPT_TPL = (
    "You are a news editor. Given JSON article metadata, group them into clusters where each cluster covers exactly ONE specific, distinct news story or event.\\n\\n"
    "STRICT CLUSTERING RULES:\\n"
    "- Only group articles covering the EXACT SAME specific incident, announcement, or event\\n"
    "- Different vulnerabilities/flaws, even in similar technologies, MUST be separate clusters\\n"
    "- Different company announcements MUST be separate clusters\\n"
    "- General topics like 'confidential computing news' should NOT be clustered together\\n"
    "- Articles about related but distinct events MUST be in different clusters\\n"
    "- When in doubt, keep articles SEPARATE\\n\\n"
    "EXAMPLES OF WHAT NOT TO CLUSTER:\\n"
    "- 'Intel SGX vulnerability' + 'AMD SEV vulnerability' → SEPARATE (different flaws)\\n"
    "- 'Microsoft AI announcement' + 'Google AI announcement' → SEPARATE (different companies)\\n"
    "- 'Remote attestation flaw A' + 'Remote attestation flaw B' → SEPARATE (different flaws)\\n\\n"
    "Each cluster should represent one specific factual event, not a general topic.\\n\\n"
    'Respond with ONLY JSON: {{"clusters": [{{"label": "Specific event description", "ids": [1, 2]}}, ...]}}\\n\\n'
    "Articles: {{articles_json}}"
)'''
            
            content = content[:start_idx] + new_prompt + content[end_idx:]
            fixes_applied.append("Updated AI clustering prompt with stricter rules")
        
        # Write back the fixed content
        with open('crawler.py', 'w') as f:
            f.write(content)
            
        print("✅ Fixes applied successfully!")
        
    except Exception as e:
        print(f"❌ Error applying fixes: {e}")
        return False
    
    print("\nFIXES APPLIED:")
    for i, fix in enumerate(fixes_applied, 1):
        print(f"{i}. {fix}")
    
    return True


def main():
    """Main function to fix clustering issues"""
    print("🚨 CC NEWS CRAWLER CLUSTERING FIX TOOL")
    print("=" * 60)
    
    print("This tool will:")
    print("1. Apply conservative clustering parameter fixes")
    print("2. Improve AI clustering prompt")
    print("3. Add diagnostic capabilities")
    print()
    
    response = input("Apply clustering fixes? (y/n): ").lower().strip()
    if response == 'y':
        success = apply_clustering_fixes()
        if success:
            print("\n🎉 CLUSTERING FIXES APPLIED!")
            print()
            print("CHANGES MADE:")
            print("✅ Reduced date window: 5 days → 2 days")
            print("✅ Increased Jaccard threshold: 0.35 → 0.6")
            print("✅ Improved AI clustering prompt with strict rules")
            print()
            print("NEXT STEPS:")
            print("1. Test with: python3 crawler.py --start 2025-12-01 --end 2025-12-31")
            print("2. Check clustering quality in output")
            print("3. Adjust parameters if needed")
        
        return success
    else:
        print("No changes made.")
        return False


if __name__ == '__main__':
    main()