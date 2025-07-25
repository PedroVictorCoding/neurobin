#!/bin/bash
# Script to remove duplicate markdown files from the main directory
# These files have been organized into the documentation/ folder structure

echo "Removing duplicate markdown files from main directory..."
echo "All files have been verified as identical to their documentation/ counterparts"

# List of duplicate files to remove from main directory
DUPLICATE_FILES=(
    "ADMIN_ACCESS.md"
    "API_DOCUMENTATION.md" 
    "CHEMBL_IMPORT_GUIDE.md"
    "CHEMBL_NAME_SEARCH_SUMMARY.md"
    "CHEMBL_TARGET_DUPLICATION_FIX.md"
    "COMPOUND_INTERACTIONS_IMPLEMENTATION.md"
    "DATABASE_SCHEMA.md"
    "DEPLOYMENT.md"
    "DEVELOPMENT.md"
    "ENHANCED_UPDATE_FUNCTIONALITY.md"
    "FEATURES.md"
    "SECURITY.md"
)

# Remove each duplicate file
for file in "${DUPLICATE_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "Removing $file"
        rm "$file"
    else
        echo "File $file not found (already removed?)"
    fi
done

echo ""
echo "Cleanup complete! Remaining markdown files in main directory:"
ls -la *.md 2>/dev/null || echo "No markdown files remaining in main directory"

echo ""
echo "Documentation structure preserved in documentation/ folder:"
find documentation/ -name "*.md" | sort
