#!/usr/bin/env python3
"""
Master Data Population Script for NeuroeBin
Orchestrates the complete data population pipeline:
1. Comprehensive compound data from ChEMBL
2. Target-compound interactions
3. Pathway data from Reactome
4. Compound-compound interactions
5. Pathway effects computation

Usage:
    python run_full_population.py [options]
"""

import os
import sys
import time
import argparse
import subprocess
from datetime import datetime


def run_command(command, description, check_output=False):
    """Run a Django management command"""
    print(f"\n🚀 {description}")
    print("=" * 60)
    print(f"Command: {command}")
    print("-" * 60)
    
    start_time = time.time()
    
    try:
        if check_output:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True)
            print(result.stdout)
            if result.stderr:
                print(f"Warnings: {result.stderr}")
        else:
            result = subprocess.run(command, shell=True, check=True)
        
        duration = time.time() - start_time
        print(f"✅ Completed in {duration:.2f} seconds")
        return True
        
    except subprocess.CalledProcessError as e:
        duration = time.time() - start_time
        print(f"❌ Failed after {duration:.2f} seconds")
        print(f"Error: {e}")
        if hasattr(e, 'stdout') and e.stdout:
            print(f"Output: {e.stdout}")
        if hasattr(e, 'stderr') and e.stderr:
            print(f"Error output: {e.stderr}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Run complete NeuroeBin data population')
    
    # Pipeline control
    parser.add_argument('--compounds-only', action='store_true', 
                       help='Only populate compounds')
    parser.add_argument('--interactions-only', action='store_true',
                       help='Only populate interactions')
    parser.add_argument('--pathways-only', action='store_true',
                       help='Only populate pathways')
    parser.add_argument('--skip-pathways', action='store_true',
                       help='Skip pathway data (faster)')
    parser.add_argument('--skip-effects', action='store_true',
                       help='Skip pathway effects computation')
    
    # Performance options
    parser.add_argument('--batch-size', type=int, default=100,
                       help='Batch size for API requests (default: 100)')
    parser.add_argument('--delay', type=float, default=0.1,
                       help='Delay between API calls in seconds (default: 0.1)')
    parser.add_argument('--max-compounds', type=int,
                       help='Maximum compounds to process (for testing)')
    
    # Database options
    parser.add_argument('--migrate', action='store_true',
                       help='Run migrations before starting')
    parser.add_argument('--backup', action='store_true',
                       help='Create database backup before starting')
    
    args = parser.parse_args()
    
    # Set up paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    core_dir = os.path.join(script_dir, 'core')
    
    if not os.path.exists(core_dir):
        print("❌ Error: 'core' directory not found. Run this script from the project root.")
        sys.exit(1)
    
    # Change to core directory
    os.chdir(core_dir)
    
    # Check for virtual environment
    venv_python = "../venv/bin/python"
    if not os.path.exists(venv_python):
        print("❌ Error: Virtual environment not found at ../venv/")
        print("Please ensure the virtual environment is set up correctly.")
        sys.exit(1)
    
    print("🧬 NEUROBIN COMPREHENSIVE DATA POPULATION")
    print("=" * 80)
    print(f"Started at: {datetime.now()}")
    print(f"Working directory: {os.getcwd()}")
    print(f"Python executable: {venv_python}")
    print("")
    
    # Build base command
    base_cmd = f"{venv_python} manage.py"
    
    # Step 1: Migrations (if requested)
    if args.migrate:
        if not run_command(f"{base_cmd} migrate", "Running database migrations"):
            print("❌ Migration failed. Exiting.")
            sys.exit(1)
    
    # Step 2: Database backup (if requested)
    if args.backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"db_backup_{timestamp}.sqlite3"
        if not run_command(f"cp db.sqlite3 {backup_file}", f"Creating database backup: {backup_file}"):
            print("⚠️  Backup failed, but continuing...")
    
    # Step 3: Build population command
    pop_cmd = f"{base_cmd} populate_all_data"
    
    # Add options to population command
    if args.compounds_only:
        pop_cmd += " --compounds-only"
    if args.interactions_only:
        pop_cmd += " --interactions-only"
    if args.pathways_only:
        pop_cmd += " --pathways-only"
    if args.skip_pathways:
        pop_cmd += " --skip-pathways"
    
    pop_cmd += f" --batch-size {args.batch_size}"
    pop_cmd += f" --delay {args.delay}"
    
    if args.max_compounds:
        pop_cmd += f" --max-compounds {args.max_compounds}"
    
    # Step 4: Run main population
    success = run_command(pop_cmd, "Running comprehensive data population")
    
    if not success:
        print("❌ Data population failed.")
        sys.exit(1)
    
    # Step 5: Compute pathway effects (if not skipped and not partial run)
    if not args.skip_effects and not any([args.compounds_only, args.interactions_only]):
        effects_cmd = f"{base_cmd} compute_pathway_effects --batch-size {args.batch_size}"
        if not args.pathways_only:  # Only recompute if we just populated new data
            effects_cmd += " --recompute"
        
        run_command(effects_cmd, "Computing pathway effects")
    
    # Step 6: Final statistics
    print("\n📊 FINAL DATABASE STATISTICS")
    print("=" * 80)
    
    stats_cmd = f"{base_cmd} shell -c \""
    stats_cmd += "from compounds.models import *; "
    stats_cmd += "print(f'Compounds: {Compound.objects.count():,}'); "
    stats_cmd += "print(f'Targets: {Target.objects.count():,}'); "
    stats_cmd += "print(f'Compound-Target Interactions: {CompoundTargetInteraction.objects.count():,}'); "
    stats_cmd += "print(f'Compound-Compound Interactions: {CompoundToCompoundTargetInteraction.objects.count():,}'); "
    stats_cmd += "print(f'Target-Pathway Interactions: {TargetPathwayInteraction.objects.count():,}'); "
    stats_cmd += "print(f'Compound Pathway Effects: {CompoundPathwayEffect.objects.count():,}');"
    stats_cmd += "\""
    
    run_command(stats_cmd, "Final database statistics", check_output=True)
    
    print("\n🎉 DATA POPULATION PIPELINE COMPLETED!")
    print("=" * 80)
    print(f"Finished at: {datetime.now()}")
    print("\nYour NeuroeBin database is now populated with comprehensive")
    print("compound, interaction, and pathway data!")
    print("\n🚀 Ready for:")
    print("  • Pathway visualization")
    print("  • Compound interaction analysis")
    print("  • Drug mechanism exploration")
    print("  • Biological pathway mapping")


if __name__ == "__main__":
    main()
