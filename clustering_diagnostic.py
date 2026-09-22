#!/usr/bin/env python3
"""
Diagnostic tool to analyze clustering output and identify problematic groupings.
Run this after generating a report to check for over-clustering issues.
"""

import re
import sys
from urllib.parse import urlparse

def analyze_clustering_report(report_path):
    """Analyze a clustering report and identify potentially problematic clusters"""
    print(f"🔍 ANALYZING CLUSTERING REPORT: {report_path}")
    print("=" * 60)
    
    try:
        with open(report_path, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ Report file not found: {report_path}")
        return
    
    # Find all cluster headings and their articles
    clusters = []
    current_cluster = None
    in_cluster = False
    
    lines = content.split('\n')
    for line in lines:
        # Check for cluster heading
        if line.startswith('**') and line.endswith('**') and len(line) > 4:
            if current_cluster:
                clusters.append(current_cluster)
            current_cluster = {
                'heading': line.strip('*'),
                'articles': []
            }
            in_cluster = True
        elif in_cluster and line.strip().startswith('- ['):
            # Extract article info
            title_match = re.search(r'\[([^\]]+)\]', line)
            url_match = re.search(r'\]\(([^\)]+)\)', line)
            publisher_match = re.search(r'\(Publisher: ([^,\)]+)', line)
            
            if title_match:
                article = {
                    'title': title_match.group(1),
                    'url': url_match.group(1) if url_match else '',
                    'publisher': publisher_match.group(1) if publisher_match else '',
                    'line': line.strip()
                }
                current_cluster['articles'].append(article)
        elif line.strip() == '' or line.startswith('#'):
            if current_cluster and in_cluster:
                in_cluster = False
    
    if current_cluster:
        clusters.append(current_cluster)
    
    # Analyze clusters for problems
    problematic_clusters = []
    
    for cluster in clusters:
        if len(cluster['articles']) < 2:
            continue  # Single articles are fine
        
        # Check for potential problems
        problems = []
        articles = cluster['articles']
        
        # Problem 1: Multiple different domains with very different titles
        domains = set()
        for article in articles:
            if article['url']:
                try:
                    domain = urlparse(article['url']).netloc.lower()
                    domains.add(domain)
                except:
                    pass
        
        if len(domains) > 3:
            problems.append(f"Too many domains ({len(domains)}): {list(domains)[:5]}")
        
        # Problem 2: Very different article titles (low similarity)
        titles = [article['title'] for article in articles]
        if len(titles) > 1:
            # Simple word overlap check
            all_words = set()
            for title in titles:
                words = set(title.lower().split())
                all_words.update(words)
            
            common_words = set(titles[0].lower().split())
            for title in titles[1:]:
                common_words &= set(title.lower().split())
            
            if len(common_words) == 0:
                problems.append("No common words between article titles")
            elif len(common_words) < 2:
                problems.append(f"Very few common words: {list(common_words)}")
        
        # Problem 3: Different technical topics (keywords that suggest different stories)
        conflicting_keywords = [
            (['intel', 'sgx'], ['amd', 'sev']),
            (['microsoft'], ['google']),
            (['vulnerability', 'flaw'], ['announcement', 'release']),
            (['hardware'], ['software']),
            (['attack'], ['launch', 'announcement'])
        ]
        
        for keywords1, keywords2 in conflicting_keywords:
            has_keywords1 = any(any(kw in article['title'].lower() for kw in keywords1) for article in articles)
            has_keywords2 = any(any(kw in article['title'].lower() for kw in keywords2) for article in articles)
            
            if has_keywords1 and has_keywords2:
                problems.append(f"Conflicting topics: {keywords1} vs {keywords2}")
        
        if problems:
            problematic_clusters.append({
                'cluster': cluster,
                'problems': problems
            })
    
    # Report findings
    print(f"📊 ANALYSIS RESULTS:")
    print(f"Total clusters analyzed: {len(clusters)}")
    print(f"Clusters with multiple articles: {len([c for c in clusters if len(c['articles']) > 1])}")
    print(f"Potentially problematic clusters: {len(problematic_clusters)}")
    print()
    
    if problematic_clusters:
        print("🚨 PROBLEMATIC CLUSTERS FOUND:")
        print()
        for i, item in enumerate(problematic_clusters, 1):
            cluster = item['cluster']
            problems = item['problems']
            
            print(f"PROBLEM CLUSTER {i}: {cluster['heading']}")
            print(f"Articles: {len(cluster['articles'])}")
            print(f"Issues: {', '.join(problems)}")
            print()
            for j, article in enumerate(cluster['articles'], 1):
                print(f"  {j}. {article['title']}")
                print(f"     Publisher: {article['publisher']}")
                print(f"     URL: {article['url'][:80]}...")
                print()
            print("-" * 60)
            print()
    else:
        print("✅ No obvious clustering problems detected!")
    
    return problematic_clusters

if __name__ == '__main__':
    if len(sys.argv) > 1:
        report_file = sys.argv[1]
    else:
        # Look for the most recent report file
        import glob
        reports = glob.glob('*-clustering-analysis.md') + glob.glob('report-*.md')
        if reports:
            report_file = max(reports, key=lambda f: f)
            print(f"Using most recent report: {report_file}")
        else:
            print("Usage: python3 clustering_diagnostic.py <report-file.md>")
            sys.exit(1)
    
    analyze_clustering_report(report_file)
