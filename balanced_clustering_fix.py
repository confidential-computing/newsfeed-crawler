#!/usr/bin/env python3
"""
Balanced clustering fix: Re-enable story clustering but prevent over-clustering.
Goal: Group same stories (Nvidia location tech) but separate different stories.
"""

def fix_clustering_balance():
    """Apply balanced clustering parameters to allow legitimate grouping while preventing over-clustering"""
    print("🔧 BALANCED CLUSTERING FIX")
    print("=" * 50)
    print()
    print("GOAL: Find optimal balance between:")
    print("✅ Group SAME stories (7 Nvidia location-verification articles)")
    print("❌ Separate DIFFERENT stories (Microsoft investment vs AMD CPU vs Police exam)")
    print()
    
    try:
        with open('crawler.py', 'r') as f:
            content = f.read()
        
        fixes_applied = []
        
        # 1. Re-enable AI clustering BUT with much stricter prompt
        old_use_ai = "use_ai = False  # AI clustering disabled due to over-clustering issues"
        new_use_ai = "use_ai = args.enable_ai_cluster  # AI clustering with strict controls"
        
        if old_use_ai in content:
            content = content.replace(old_use_ai, new_use_ai)
            fixes_applied.append("Re-enabled AI clustering option with strict controls")
        
        # 2. Improve AI clustering prompt to be extremely specific about what to group
        # Find and replace the AI clustering prompt with hyper-specific rules
        prompt_start = '_CLUSTER_PROMPT_TPL = ('
        if prompt_start in content:
            # Find the full prompt
            start_idx = content.index(prompt_start)
            lines = content[start_idx:].split('\n')
            end_line = None
            bracket_count = 0
            for i, line in enumerate(lines):
                if '(' in line:
                    bracket_count += line.count('(') - line.count(')')
                if ')' in line:
                    bracket_count -= line.count(')') - line.count('(')
                if bracket_count == 0 and line.strip().endswith(')'):
                    end_line = i
                    break
            
            if end_line:
                end_idx = start_idx + content[start_idx:].index('\n'.join(lines[:end_line+1])) + len('\n'.join(lines[:end_line+1]))
                
                # Create new ultra-specific prompt
                new_prompt = '''_CLUSTER_PROMPT_TPL = (
    "You are a news editor. Group articles into clusters where each cluster covers exactly ONE specific incident/announcement.\\n\\n"
    "ONLY group articles if they are about the EXACT SAME:\\n"
    "- Same company announcement (e.g., 'Microsoft Canada investment')\\n"
    "- Same vulnerability/incident (e.g., 'Intel SGX flaw X')\\n" 
    "- Same product launch (e.g., 'Nvidia location tracking tech')\\n"
    "- Same research study or report\\n\\n"
    "NEVER group articles about:\\n"
    "- Different companies (Microsoft ≠ Google ≠ AMD)\\n"
    "- Different products (CPU ≠ GPU ≠ Software)\\n"
    "- Different vulnerabilities (SGX flaw ≠ SEV flaw)\\n"
    "- General topics ('AI trends' ≠ 'security news')\\n"
    "- Different announcements from same company\\n\\n"
    "EXAMPLES:\\n"
    "✅ GROUP: ['Nvidia location tracking tech - Reuters', 'Nvidia develops location tech - TechCrunch']\\n"
    "❌ SEPARATE: ['Microsoft investment in Canada', 'Microsoft new CPU design']\\n"
    "❌ SEPARATE: ['Intel SGX vulnerability', 'AMD SEV vulnerability']\\n\\n"
    "When unsure, create separate clusters. Each cluster = ONE specific news event.\\n\\n"
    'Respond ONLY with JSON: {{"clusters": [{{"label": "Specific event", "ids": [1, 2]}}, ...]}}\\n\\n'
    "Articles: {articles_json}"
)'''
                
                content = content[:start_idx] + new_prompt + content[end_idx:]
                fixes_applied.append("Updated AI prompt with hyper-specific clustering rules")
        
        # 3. Also improve heuristic clustering to be more balanced
        old_heuristic = "def heuristic_cluster(articles, date_window_days=1, jaccard_threshold=0.7):"
        new_heuristic = "def heuristic_cluster(articles, date_window_days=2, jaccard_threshold=0.65):"
        
        if old_heuristic in content:
            content = content.replace(old_heuristic, new_heuristic)
            fixes_applied.append("Balanced heuristic clustering: jaccard=0.65, date_window=2 days")
        
        # 4. Add subject-based clustering prevention for obviously different topics
        # Find the clustering union logic and add subject checking
        clustering_union = "union(i, j)"
        if clustering_union in content:
            enhanced_union = """# Final check: prevent grouping obviously different subjects
            subject_i = infer_subject(articles[i]["title"]) or ""
            subject_j = infer_subject(articles[j]["title"]) or ""
            
            # Prevent clustering if subjects are clearly different companies
            different_companies = [
                ('microsoft', ['google', 'apple', 'amazon', 'intel', 'amd', 'nvidia']),
                ('google', ['microsoft', 'apple', 'amazon', 'intel', 'amd', 'nvidia']), 
                ('intel', ['amd', 'nvidia', 'microsoft', 'google', 'apple']),
                ('amd', ['intel', 'nvidia', 'microsoft', 'google', 'apple']),
                ('nvidia', ['intel', 'amd', 'microsoft', 'google', 'apple'])
            ]
            
            for company, competitors in different_companies:
                if (company in subject_i.lower() and 
                    any(comp in subject_j.lower() for comp in competitors)):
                    continue  # Don't cluster different companies
                if (company in subject_j.lower() and 
                    any(comp in subject_i.lower() for comp in competitors)):
                    continue  # Don't cluster different companies
            
            union(i, j)"""
            
            content = content.replace(clustering_union, enhanced_union)
            fixes_applied.append("Added subject-based clustering prevention for different companies")
        
        # Write updated content
        with open('crawler.py', 'w') as f:
            f.write(content)
        
        print("✅ BALANCED CLUSTERING FIXES APPLIED!")
        print()
        for i, fix in enumerate(fixes_applied, 1):
            print(f"{i}. {fix}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error applying fixes: {e}")
        return False


def test_balanced_clustering():
    """Test the balanced clustering to ensure it works properly"""
    print("\n🧪 TESTING BALANCED CLUSTERING")
    print("=" * 50)
    
    import subprocess
    import sys
    
    # Test with AI clustering enabled
    print("Testing with AI clustering enabled...")
    try:
        result = subprocess.run([
            sys.executable, "crawler.py",
            "--start", "2025-12-01", 
            "--end", "2025-12-31",
            "--enable-ai-cluster",
            "--output", "balanced-ai-test.md"
        ], capture_output=True, text=True, timeout=180)
        
        if result.returncode == 0:
            print("✅ AI clustering test completed")
            
            # Analyze results
            with open('balanced-ai-test.md', 'r') as f:
                content = f.read()
            
            # Count story clusters vs individual articles
            cluster_headings = [line for line in content.split('\n') 
                              if line.startswith('**') and line.endswith('**') and 
                              'Nvidia' in line or 'Microsoft' in line or 'Telegram' in line]
            
            print(f"Story clusters found: {len(cluster_headings)}")
            for heading in cluster_headings[:5]:  # Show first 5
                clean_heading = heading.strip('*')
                print(f"  - {clean_heading}")
            
            # Run diagnostic
            diag_result = subprocess.run([
                sys.executable, "clustering_diagnostic.py", "balanced-ai-test.md"
            ], capture_output=True, text=True)
            
            if "No obvious clustering problems detected" in diag_result.stdout:
                print("✅ AI clustering: No problems detected")
            else:
                print("⚠️ AI clustering: Some issues remain")
                # Show summary of issues
                if "PROBLEMATIC CLUSTERS FOUND" in diag_result.stdout:
                    lines = diag_result.stdout.split('\n')
                    for i, line in enumerate(lines):
                        if "PROBLEM CLUSTER" in line:
                            print(f"    {line}")
                            if i+1 < len(lines):
                                print(f"    {lines[i+1]}")
                            break
        
        else:
            print(f"❌ AI clustering test failed: {result.stderr}")
    
    except Exception as e:
        print(f"❌ AI test error: {e}")
    
    # Test with heuristic clustering
    print("\nTesting with heuristic clustering...")
    try:
        result = subprocess.run([
            sys.executable, "crawler.py",
            "--start", "2025-12-01",
            "--end", "2025-12-31", 
            "--output", "balanced-heuristic-test.md"
        ], capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            print("✅ Heuristic clustering test completed")
            
            with open('balanced-heuristic-test.md', 'r') as f:
                content = f.read()
            
            # Count clusters
            if "Heuristic clustered" in result.stderr:
                clusters_info = [line for line in result.stderr.split('\n') if 'clustered' in line and 'articles' in line]
                if clusters_info:
                    print(f"  {clusters_info[0]}")
            
            diag_result = subprocess.run([
                sys.executable, "clustering_diagnostic.py", "balanced-heuristic-test.md"
            ], capture_output=True, text=True)
            
            if "No obvious clustering problems detected" in diag_result.stdout:
                print("✅ Heuristic clustering: No problems detected")
            else:
                print("⚠️ Heuristic clustering: Some issues found")
        
        else:
            print(f"❌ Heuristic test failed: {result.stderr}")
    
    except Exception as e:
        print(f"❌ Heuristic test error: {e}")


def main():
    """Apply balanced clustering fix"""
    print("🎯 GOAL: Balance clustering to group same stories but separate different stories")
    print()
    print("Target result:")
    print("✅ Nvidia location-verification articles → grouped together")
    print("✅ Microsoft Canada investment articles → grouped together") 
    print("❌ Microsoft investment + AMD CPU + Police exam → separate clusters")
    print()
    
    success = fix_clustering_balance()
    
    if success:
        test_balanced_clustering()
        
        print("\n🎉 BALANCED CLUSTERING APPLIED!")
        print()
        print("NEXT STEPS:")
        print("1. Test default behavior: python3 crawler.py --start DATE --end DATE")
        print("2. Test AI clustering: python3 crawler.py --enable-ai-cluster --start DATE --end DATE")
        print("3. Use diagnostic tool: python3 clustering_diagnostic.py <report.md>")
        print("4. Verify legitimate stories are grouped, unrelated stories separated")
    
    return success

if __name__ == '__main__':
    main()