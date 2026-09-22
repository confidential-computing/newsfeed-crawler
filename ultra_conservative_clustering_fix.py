#!/usr/bin/env python3
"""
Ultra-conservative clustering fix to prevent any incorrect groupings.
This implements very strict clustering rules to ensure different stories never get grouped together.
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def apply_ultra_conservative_clustering():
    """Apply ultra-conservative clustering parameters to prevent over-clustering"""
    print("🚨 APPLYING ULTRA-CONSERVATIVE CLUSTERING FIXES")
    print("=" * 60)
    
    try:
        with open('crawler.py', 'r') as f:
            content = f.read()
        
        fixes_applied = []
        
        # 1. Make heuristic clustering extremely conservative
        old_heuristic = "def heuristic_cluster(articles, date_window_days=2, jaccard_threshold=0.6):"
        new_heuristic = "def heuristic_cluster(articles, date_window_days=1, jaccard_threshold=0.85):"
        
        if old_heuristic in content:
            content = content.replace(old_heuristic, new_heuristic)
            fixes_applied.append("Heuristic clustering: date_window=2→1 day, jaccard=0.6→0.85")
        
        # 2. Update AI clustering prompt to be even more strict
        old_prompt_section = '- When in doubt, keep articles SEPARATE\\n\\n'
        new_prompt_section = '''- When in doubt, keep articles SEPARATE\\n
- NEVER group articles about different vulnerabilities\\n
- NEVER group articles about different companies\\n
- NEVER group articles from different domains unless 100% identical\\n
- NEVER group articles with different technical details\\n\\n'''
        
        if old_prompt_section in content:
            content = content.replace(old_prompt_section, new_prompt_section)
            fixes_applied.append("AI prompt: Added additional strict separation rules")
        
        # 3. Add domain-based clustering prevention in heuristic clustering
        # Find the clustering logic that checks jaccard similarity
        clustering_check = """if len(t_i & t_j) / union_size < jaccard_threshold:
                continue
            union(i, j)"""
        
        new_clustering_check = """if len(t_i & t_j) / union_size < jaccard_threshold:
                continue
            
            # Ultra-conservative: prevent clustering across different domains
            # unless titles are nearly identical (>95% similarity)
            url1 = articles[i].get("url", "")
            url2 = articles[j].get("url", "")
            if url1 and url2:
                try:
                    from urllib.parse import urlparse
                    domain1 = urlparse(url1).netloc.lower()
                    domain2 = urlparse(url2).netloc.lower()
                    
                    if domain1 != domain2:
                        # Different domains require 95% title similarity
                        if len(t_i & t_j) / union_size < 0.95:
                            continue
                except:
                    pass
            
            union(i, j)"""
        
        if clustering_check in content:
            content = content.replace(clustering_check, new_clustering_check)
            fixes_applied.append("Added domain-based clustering prevention (95% similarity required)")
        
        # Write the updated content
        with open('crawler.py', 'w') as f:
            f.write(content)
        
        print("✅ ULTRA-CONSERVATIVE CLUSTERING FIXES APPLIED!")
        print()
        for i, fix in enumerate(fixes_applied, 1):
            print(f"{i}. {fix}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error applying fixes: {e}")
        return False


def create_clustering_diagnostic_tool():
    """Create a tool to identify problematic clusters after running the crawler"""
    diagnostic_code = '''#!/usr/bin/env python3
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
    
    lines = content.split('\\n')
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
            title_match = re.search(r'\\[([^\\]]+)\\]', line)
            url_match = re.search(r'\\]\\(([^\\)]+)\\)', line)
            publisher_match = re.search(r'\\(Publisher: ([^,\\)]+)', line)
            
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
'''

    with open('clustering_diagnostic.py', 'w') as f:
        f.write(diagnostic_code)
    
    print("✅ Created clustering diagnostic tool: clustering_diagnostic.py")


def main():
    """Apply ultra-conservative clustering fixes and create diagnostic tools"""
    print("🔧 ULTRA-CONSERVATIVE CLUSTERING FIX")
    print("This will apply very strict clustering rules to prevent any over-clustering")
    print()
    
    # Apply fixes
    success = apply_ultra_conservative_clustering()
    
    if success:
        # Create diagnostic tool
        create_clustering_diagnostic_tool()
        
        print()
        print("🎯 NEXT STEPS:")
        print("1. Test clustering: python3 crawler.py --start 2025-12-01 --end 2025-12-31")
        print("2. Run diagnostic: python3 clustering_diagnostic.py <report-file.md>")
        print("3. Check for remaining clustering problems")
        print()
        print("📋 ULTRA-CONSERVATIVE SETTINGS APPLIED:")
        print("✅ Date window: 1 day (was 2 days)")
        print("✅ Jaccard threshold: 0.85 (was 0.6)")
        print("✅ Cross-domain clustering: requires 95% similarity")
        print("✅ Enhanced AI prompt with stricter rules")
        
    return success

if __name__ == '__main__':
    main()