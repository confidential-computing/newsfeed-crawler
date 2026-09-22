#!/usr/bin/env python3
"""
Apply a balanced clustering fix that groups obvious same-stories while preventing over-clustering.
Based on analysis, L&T Vyoma + Fortanix articles should cluster together.
"""

def apply_balanced_clustering_fix():
    """Apply balanced clustering parameters to fix under-clustering"""
    print("🔧 APPLYING BALANCED CLUSTERING FIX")
    print("=" * 50)
    print()
    print("ANALYSIS:")
    print("  - L&T Vyoma + Fortanix stories have 0.438 similarity (should cluster)")
    print("  - Different stories have 0.000 similarity (correctly separate)")
    print("  - Current 0.7 threshold is too strict")
    print("  - Optimal threshold: ~0.3-0.4 for heuristic clustering")
    print()
    
    try:
        with open('crawler.py', 'r') as f:
            content = f.read()
        
        fixes_applied = []
        
        # 1. Lower the Jaccard threshold to allow legitimate clustering
        # Current ultra-conservative threshold prevents same stories from clustering
        old_threshold_pattern = r"def heuristic_cluster\(articles, date_window_days=\d+, jaccard_threshold=0\.\d+\):"
        new_heuristic = "def heuristic_cluster(articles, date_window_days=1, jaccard_threshold=0.4):"
        
        import re
        if re.search(old_threshold_pattern, content):
            content = re.sub(old_threshold_pattern, new_heuristic, content)
            fixes_applied.append("Lowered Jaccard threshold from 0.7+ to 0.4 for legitimate clustering")
        
        # 2. Ensure the ultra-conservative domain check doesn't prevent clustering when not needed
        # The current logic requires 95% similarity for different domains, which is preventing clustering
        old_domain_check = '''            # Ultra-conservative: prevent clustering across different domains
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
                    pass'''
        
        new_domain_check = '''            # Conservative cross-domain clustering: require higher similarity for different domains
            # This prevents over-clustering while allowing legitimate same-story grouping
            url1 = articles[i].get("url", "")
            url2 = articles[j].get("url", "")
            if url1 and url2:
                try:
                    from urllib.parse import urlparse
                    domain1 = urlparse(url1).netloc.lower()
                    domain2 = urlparse(url2).netloc.lower()
                    
                    if domain1 != domain2:
                        # Different domains require higher similarity (0.6 vs 0.4)
                        if len(t_i & t_j) / union_size < 0.6:
                            continue
                except:
                    pass'''
        
        if old_domain_check in content:
            content = content.replace(old_domain_check, new_domain_check)
            fixes_applied.append("Relaxed cross-domain clustering from 95% to 60% similarity")
        
        # 3. Re-enable AI clustering option but keep it opt-in for safety
        old_ai_default = "use_ai = False  # Disabled by default due to over-clustering"
        new_ai_default = "use_ai = args.enable_ai_cluster  # AI clustering available but opt-in"
        
        if old_ai_default in content:
            content = content.replace(old_ai_default, new_ai_default) 
            fixes_applied.append("Made AI clustering opt-in via --enable-ai-cluster flag")
        
        # Write the fixed content
        with open('crawler.py', 'w') as f:
            f.write(content)
        
        print("✅ FIXES APPLIED:")
        for fix in fixes_applied:
            print(f"  - {fix}")
        
        if not fixes_applied:
            print("ℹ️  No changes needed - patterns not found in current code")
        
        print()
        print("🧪 TESTING RECOMMENDATION:")
        print("  Run: python3 crawler.py --start 2026-07-08 --end 2026-07-09 --output test-balanced.md")
        print("  Expected: L&T Vyoma + Fortanix articles should cluster into 1-2 groups instead of 6 separate")
        
        return True
        
    except Exception as e:
        print(f"❌ Error applying fix: {e}")
        return False

if __name__ == "__main__":
    apply_balanced_clustering_fix()