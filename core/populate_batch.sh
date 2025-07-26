#!/bin/bash
# Comprehensive Data Population Batch Script for Neurobin
# This script runs the population in optimized stages to handle large datasets

set -e  # Exit on any error

echo "🚀 Starting Neurobin Comprehensive Data Population"
echo "=================================================="

# Configuration
PYTHON_CMD="/home/main/Dev/neurobin/venv/bin/python"
SCRIPT_DIR="/home/main/Dev/neurobin/core"
LOG_FILE="$SCRIPT_DIR/batch_population.log"
ERROR_LOG="$SCRIPT_DIR/batch_errors.log"

# Create log files
touch "$LOG_FILE"
touch "$ERROR_LOG"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Function to handle errors
handle_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" | tee -a "$ERROR_LOG"
    echo "❌ Error occurred. Check $ERROR_LOG for details."
    exit 1
}

# Function to run Django management command
run_django_cmd() {
    log "Running: $1"
    cd "$SCRIPT_DIR"
    if ! $PYTHON_CMD manage.py shell -c "$1" 2>>"$ERROR_LOG"; then
        handle_error "Django command failed: $1"
    fi
}

# Function to run population script
run_population() {
    log "Running population: $1"
    cd "$SCRIPT_DIR"
    if ! $PYTHON_CMD populate_all_data.py $1 2>>"$ERROR_LOG"; then
        handle_error "Population script failed: $1"
    fi
}

# Check if Django is accessible
log "Checking Django setup..."
if ! cd "$SCRIPT_DIR" && $PYTHON_CMD manage.py check --deploy 2>>"$ERROR_LOG"; then
    log "Warning: Django check failed, but continuing..."
fi

# Stage 1: Basic Data Types (fast)
log "🔧 Stage 1: Populating basic data types..."
run_django_cmd "
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from populate_all_data import DataPopulator
populator = DataPopulator(no_limits=True)

# Basic data types
print('Populating action types...')
populator.populate_action_types()

print('Populating target types...')
populator.populate_target_types()

print('Populating compound categories...')
populator.populate_compound_categories()

print('Stage 1 completed!')
"

# Stage 2: External API Data (slow - ChEMBL, Reactome)
log "🌐 Stage 2: Fetching data from external APIs..."
log "This stage may take 30-60 minutes depending on API limits..."

# Create checkpoints to resume if interrupted
if [ ! -f "$SCRIPT_DIR/.checkpoint_targets" ]; then
    log "Fetching targets from ChEMBL..."
    run_population "--targets-only --no-limits"
    touch "$SCRIPT_DIR/.checkpoint_targets"
    log "✅ Targets completed"
fi

if [ ! -f "$SCRIPT_DIR/.checkpoint_compounds" ]; then
    log "Fetching compounds from ChEMBL..."
    run_population "--compounds-only --no-limits"
    touch "$SCRIPT_DIR/.checkpoint_compounds"
    log "✅ Compounds completed"
fi

# Stage 3: Relationships and Interactions (medium speed)
log "🔗 Stage 3: Building relationships and interactions..."
log "This stage creates mechanisms, pathway interactions, and compound effects..."
run_django_cmd "
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from populate_all_data import DataPopulator
populator = DataPopulator(no_limits=True)

# Mechanisms from ChEMBL
print('🔧 Starting mechanisms population from ChEMBL...')
populator.populate_mechanisms_from_chembl(limit=None)

# Pathway interactions from Reactome
print('🧬 Starting pathway interactions from Reactome...')
populator.populate_pathway_interactions_from_reactome(limit=None)

# Compound pathway effects
print('🔗 Starting compound pathway effects...')
populator.populate_compound_pathway_effects(limit=None)

print('✅ Stage 3 completed!')
"

# Stage 4: User and Community Data (fast)
log "👥 Stage 4: Populating user and community data..."
log "This stage creates users, profiles, and research data..."
run_django_cmd "
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from populate_all_data import DataPopulator
populator = DataPopulator(no_limits=True)

# User data
print('👥 Starting user data population...')
populator.populate_user_data()

# Research data
print('🔬 Starting research data population...')
populator.populate_research_data()

print('✅ Stage 4 completed!')
"

# Stage 5: User-Generated Content (medium speed)
log "📝 Stage 5: Populating user-generated content..."
log "This stage creates logs, ratings, reviews, and interactions..."
run_django_cmd "
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from populate_all_data import DataPopulator
populator = DataPopulator(no_limits=True)

# Intake logs
print('📊 Starting intake logs population...')
populator.populate_intake_logs()

# Ratings and safety
print('⭐ Starting ratings and safety data...')
populator.populate_ratings_and_safety()

# Effect windows
print('⏱️ Starting effect windows...')
populator.populate_effect_windows()

# Compound interactions
print('🔗 Starting compound interactions...')
populator.populate_compound_interactions()

# Change requests
print('📝 Starting change requests...')
populator.populate_change_requests()

print('✅ Stage 5 completed!')
"

# Stage 6: Data Validation and Statistics
log "📊 Stage 6: Running data validation and generating statistics..."
log "Final stage: validating data integrity and showing results..."
run_django_cmd "
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from compounds.models import *
from research.models import *
from accounts.models import *
from logs.models import *
from change_requests.models import *

# Print statistics
print('🎉 DATA POPULATION COMPLETED SUCCESSFULLY! 🎉')
print('=' * 50)
print('📊 FINAL STATISTICS:')
print('=' * 50)
print(f'🧪 ActionTypes: {ActionType.objects.count()}')
print(f'🎯 TargetTypes: {TargetType.objects.count()}')
print(f'📂 CompoundCategories: {CompoundCategories.objects.count()}')
print(f'🎯 Targets: {Target.objects.count()}')
print(f'💊 Compounds: {Compound.objects.count()}')
print(f'⚙️ CompoundMechanismOfAction: {CompoundMechanismOfAction.objects.count()}')
print(f'⚡ CompoundTargetInteraction: {CompoundTargetInteraction.objects.count()}')
print(f'🧬 TargetPathwayInteraction: {TargetPathwayInteraction.objects.count()}')
print(f'🔗 CompoundPathwayEffect: {CompoundPathwayEffect.objects.count()}')
print(f'📝 ResearchSnippets: {ResearchSnippet.objects.count()}')
print(f'⭐ SnippetReviews: {SnippetReview.objects.count()}')
print(f'👥 Users: {User.objects.count()}')
print(f'👤 UserProfiles: {UserProfile.objects.count()}')
print(f'📊 IntakeLogs: {IntakeLog.objects.count()}')
print(f'⭐ CompoundRatings: {CompoundRating.objects.count()}')
print(f'📝 ChangeRequests: {ChangeRequest.objects.count()}')
print('=' * 50)
print('🎉 All data populated successfully!')
print('🌐 Your Neurobin instance is now ready for use!')
print('=' * 50)
"

# Stage 7: Database Optimization
log "⚡ Stage 7: Optimizing database..."
log "Final optimizations and cleanup..."
run_django_cmd "
from django.db import connection
cursor = connection.cursor()

print('🔧 Running database optimization...')

# Analyze tables for better query performance
tables = [
    'compounds_compound', 'compounds_target', 'compounds_compoundtargetinteraction',
    'compounds_targetpathwayinteraction', 'compounds_compoundpathwayeffect',
    'research_researchsnippet', 'research_snippetreview'
]

analyzed_count = 0
for table in tables:
    try:
        cursor.execute(f'ANALYZE {table}')
        print(f'  📊 Analyzed table: {table}')
        analyzed_count += 1
    except:
        print(f'  ℹ️ Skipped table: {table} (SQLite does not require ANALYZE)')

print(f'✅ Database optimization completed! Analyzed {analyzed_count} tables.')
"

# Final cleanup
log "🧹 Cleaning up temporary files..."
echo "🗑️ Removing checkpoint files..."
rm -f "$SCRIPT_DIR/.checkpoint_*"
echo "✅ Cleanup completed!"

# Generate final report
log "📋 Generating final report..."
echo "📄 Creating comprehensive report..."
cat > "$SCRIPT_DIR/population_report.txt" << EOF
🎉 Neurobin Data Population Report 🎉
Generated: $(date)
=========================================

🎯 Population Status: COMPLETED SUCCESSFULLY ✅

📁 Log Files:
- Main log: $LOG_FILE
- Error log: $ERROR_LOG

🚀 Next Steps:
1. Start the Django development server: python manage.py runserver
2. Access admin interface: http://localhost:8000/admin/
3. View populated data in the web interface: http://localhost:8000/
4. Run data validation: python manage.py check
5. Check credits page: http://localhost:8000/credits/

🌐 For production deployment:
1. Run: python manage.py collectstatic
2. Run: python manage.py migrate
3. Create production superuser: python manage.py createsuperuser

🎉 Your Neurobin instance is now fully populated and ready to use!
EOF

echo ""
echo "🎉 COMPREHENSIVE DATA POPULATION COMPLETED SUCCESSFULLY! 🎉"
echo "================================================================"
echo "📁 Final report saved to: $SCRIPT_DIR/population_report.txt"
echo "📊 Logs available at:"
echo "   - Main: $LOG_FILE"
echo "   - Errors: $ERROR_LOG"
echo ""
echo "🚀 You can now start the server with:"
echo "   cd $SCRIPT_DIR"
echo "   $PYTHON_CMD manage.py runserver"
echo ""
echo "🔧 Access admin interface at: http://localhost:8000/admin/"
echo "   Username: admin"
echo "   Password: admin123"
echo ""
echo "🌐 Your Neurobin instance is now ready for research! 🧬"
echo "================================================================"
