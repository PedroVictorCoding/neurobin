#!/usr/bin/env python
"""
Demo script showing the difference between normal and slow mode timing.
"""

import time

def demonstrate_timing_modes():
    """Show timing differences between normal and slow mode."""
    
    print("=== ChEMBL Import Timing Demo ===\n")
    
    print("🏃 Normal Mode Timing:")
    print("- Batch delay: 2 seconds")
    print("- No per-compound delays")
    print("- Standard retry backoff: 1s, 2s, 4s")
    print("- Suitable for: Small imports, testing")
    
    print("\n🐌 Slow Mode Timing:")
    print("- Batch delay: 10 seconds")
    print("- Pre-compound delay: 3 seconds")
    print("- Between API calls: 2 seconds")
    print("- Between mechanisms: 1 second")
    print("- Target creation delay: 2 seconds")
    print("- Extended retry backoff: 3s, 6s, 12s")
    print("- Suitable for: Large imports, avoiding rate limits")
    
    print("\n📊 Estimated Processing Times:")
    
    # Calculate timing for different scenarios
    compounds = [1, 5, 10, 50]
    
    for count in compounds:
        # Normal mode: 2s between batches (default batch size 10)
        normal_batches = (count + 9) // 10  # Round up division
        normal_time = max(0, normal_batches - 1) * 2
        
        # Slow mode: much longer delays
        slow_batches = (count + 9) // 10
        slow_batch_time = max(0, slow_batches - 1) * 10
        slow_compound_time = count * 3  # 3s per compound
        slow_api_time = count * 4  # Estimated 2 API calls × 2s delay
        slow_total = slow_batch_time + slow_compound_time + slow_api_time
        
        print(f"  {count:2d} compounds: Normal ~{normal_time:2d}s | Slow ~{slow_total:3d}s")
    
    print("\n⚠️  When to Use Slow Mode:")
    print("- Importing >20 compounds")
    print("- Getting rate limit errors")
    print("- Running automated/background imports") 
    print("- Being respectful to ChEMBL's free API")
    
    print("\n🚀 Usage Examples:")
    print("# Fast import for testing")
    print("python manage.py import_chembl_interactions --compounds=CHEMBL25,CHEMBL154")
    print()
    print("# Slow import for large datasets")
    print("python manage.py import_chembl_interactions --all-compounds --slow-mode")
    print()
    print("# Conservative import with small batches")
    print("python manage.py import_chembl_interactions --all-compounds --slow-mode --batch-size=5")

if __name__ == '__main__':
    demonstrate_timing_modes()
