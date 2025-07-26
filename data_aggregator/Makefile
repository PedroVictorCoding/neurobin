# ChemBio Importer Makefile

.PHONY: help install test clean docs run-example init import-sample analyze

# Default target
help:
	@echo "ChemBio Importer - Available Commands:"
	@echo ""
	@echo "Setup Commands:"
	@echo "  install      - Install dependencies and package"
	@echo "  install-dev  - Install with development dependencies"
	@echo "  test         - Run functionality tests"
	@echo "  clean        - Clean build artifacts and cache"
	@echo ""
	@echo "Database Commands:"
	@echo "  init         - Initialize database tables"
	@echo "  import-sample - Import sample data (100 compounds)"
	@echo "  import-psych - Import psychoactive compounds"
	@echo "  stats        - Show database statistics"
	@echo ""
	@echo "Usage Commands:"
	@echo "  run-example  - Run basic usage example"
	@echo "  analyze      - Run database analysis"
	@echo "  demo         - Run complete demo workflow"
	@echo ""
	@echo "Development:"
	@echo "  docs         - Generate documentation"
	@echo "  lint         - Run code linting"
	@echo "  format       - Format code with black"

# Installation targets
install:
	pip install -r requirements.txt
	pip install -e .

install-dev:
	pip install -r requirements.txt
	pip install -e .
	pip install black flake8 pytest sphinx

# Testing
test:
	python test_setup.py

# Database operations
init:
	python -m chembio_importer --init-db

import-sample:
	python -m chembio_importer --from-chembl --limit 100 --slow
	python -m chembio_importer --from-reactome --slow

import-psych:
	python examples/psychoactive_compounds.py

stats:
	python -m chembio_importer --stats

# Examples
run-example:
	python examples/basic_usage.py

analyze:
	python examples/database_analysis.py

demo: init import-sample analyze
	@echo "Demo completed! Check the results above."

# Development tools
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf build/ dist/ .pytest_cache/
	rm -f *.db *.log database_summary.json

docs:
	@echo "Documentation files are in docs/ directory"
	@echo "API Reference: docs/API.md"
	@echo "Installation Guide: docs/INSTALLATION.md"  
	@echo "Usage Guide: docs/USAGE.md"

lint:
	flake8 chembio_importer/ --max-line-length=100 --ignore=E203,W503

format:
	black chembio_importer/ examples/ --line-length=100

# Quick commands for common workflows
quick-test: init
	python -m chembio_importer --compound CHEMBL25 --slow
	python -m chembio_importer --stats

# Export data
export:
	mkdir -p exports
	python -m chembio_importer --export ./exports

# Development server setup (if implementing web interface)
dev-server:
	@echo "Development server not implemented yet"
	@echo "This would start a web interface for browsing the database"

# Backup database
backup:
	@if [ -f "chem_react.db" ]; then \
		cp chem_react.db "chem_react_backup_$(shell date +%Y%m%d_%H%M%S).db"; \
		echo "Database backed up"; \
	else \
		echo "No database file found to backup"; \
	fi

# Restore from backup (use with caution)
restore:
	@echo "To restore from backup, manually copy a backup file to chem_react.db"
	@ls -la *backup*.db 2>/dev/null || echo "No backup files found"

# Show project info
info:
	@echo "ChemBio Importer Project Information:"
	@echo "======================================"
	@echo "Description: Cross-importer for ChEMBL and Reactome data"
	@echo "Version: 1.0.0"
	@echo "Python: $(shell python --version)"
	@echo "Database: $(shell ls -la *.db 2>/dev/null | wc -l) database file(s)"
	@echo "Log files: $(shell ls -la *.log 2>/dev/null | wc -l) log file(s)"
	@echo ""
	@echo "Project structure:"
	@find . -name "*.py" -not -path "./.venv/*" -not -path "./venv/*" | head -10
	@echo "..."

# Advanced import commands
import-approved:
	python -m chembio_importer --from-chembl --slow | grep -E "approval_status.*approved"

import-targets:
	python -m chembio_importer --from-reactome --slow

# Check dependencies
check-deps:
	@echo "Checking required dependencies..."
	@python -c "import chembl_webresource_client; print('✓ ChEMBL client')" 2>/dev/null || echo "✗ ChEMBL client missing"
	@python -c "import sqlalchemy; print('✓ SQLAlchemy')" 2>/dev/null || echo "✗ SQLAlchemy missing"
	@python -c "import requests; print('✓ Requests')" 2>/dev/null || echo "✗ Requests missing" 
	@python -c "import click; print('✓ Click')" 2>/dev/null || echo "✗ Click missing"
	@python -c "import rdkit; print('✓ RDKit')" 2>/dev/null || echo "✗ RDKit missing (optional)"

# Network connectivity test
check-apis:
	@echo "Testing API connectivity..."
	@curl -s -I "https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL25" | head -1 || echo "ChEMBL API unreachable"
	@curl -s -I "https://reactome.org/ContentService/data/pathways/low/entity/P04637" | head -1 || echo "Reactome API unreachable"
