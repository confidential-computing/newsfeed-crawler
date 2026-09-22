#!/usr/bin/env python3
"""Debug date parsing issues"""

from datetime import datetime, timezone
import email.utils as _eu

def _parse_pub_date(pub_str):
    """Same function as in crawler.py with debug output"""
    if not pub_str:
        print(f"Empty pub_str: '{pub_str}'")
        return None
    
    print(f"Parsing date: '{pub_str}'")
    
    try:
        result = _eu.parsedate_to_datetime(pub_str).astimezone(timezone.utc)
        print(f"  Success with email.utils: {result}")
        return result
    except Exception as e:
        print(f"  email.utils failed: {e}")
    
    try:
        result = datetime.strptime(pub_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        print(f"  Success with strptime: {result}")
        return result
    except Exception as e:
        print(f"  strptime failed: {e}")
    
    print(f"  Both methods failed")
    return None

# Test the problematic dates
test_dates = [
    "Wed, 08 Jul 2026 08:38:08 UTC",
    "Wed, 08 Jul 2026 07:46:59 UTC",
    "Wed, 08 Jul 2026 07:33:03 UTC"
]

print("=== Date Parsing Debug ===")
for date_str in test_dates:
    result = _parse_pub_date(date_str)
    print(f"Final result: {result}\n")