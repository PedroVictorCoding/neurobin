#!/usr/bin/env python3
"""
Test script to verify ChemBio Importer functionality
"""

import os
import sys
import tempfile
import logging
from pathlib import Path

# Add the project to Python path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all modules can be imported"""
    print("Testing imports...")
    
    try:
        from chembio_importer import db_manager
        print("✓ Database manager imported")
    except ImportError as e:
        print(f"✗ Database manager import failed: {e}")
        return False
    
    try:
        from chembio_importer.parsers import chembl_client, reactome_client, uniprot_client
        print("✓ API clients imported")
    except ImportError as e:
        print(f"✗ API clients import failed: {e}")
        return False
    
    try:
        from chembio_importer.models import Compound, Target, Pathway
        print("✓ Database models imported")
    except ImportError as e:
        print(f"✗ Database models import failed: {e}")
        return False
    
    try:
        from chembio_importer.__main__ import ChemBioImporter
        print("✓ Main importer imported")
    except ImportError as e:
        print(f"✗ Main importer import failed: {e}")
        return False
    
    return True

def test_database_creation():
    """Test database table creation"""
    print("\nTesting database creation...")
    
    try:
        # Use temporary database
        import tempfile
        from chembio_importer.database import DatabaseManager
        
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            temp_db_path = tmp.name
        
        # Create database manager with temp database
        db_url = f"sqlite:///{temp_db_path}"
        temp_db_manager = DatabaseManager(db_url)
        
        # Create tables
        temp_db_manager.create_tables()
        print("✓ Database tables created successfully")
        
        # Test basic operations
        with temp_db_manager.get_session() as session:
            stats = temp_db_manager.get_database_stats(session)
            print(f"✓ Database stats: {stats}")
        
        # Cleanup
        os.unlink(temp_db_path)
        return True
        
    except Exception as e:
        print(f"✗ Database creation failed: {e}")
        return False

def test_api_connectivity():
    """Test API connectivity (without making actual requests)"""
    print("\nTesting API client initialization...")
    
    try:
        from chembio_importer.parsers import chembl_client, reactome_client
        print("✓ ChEMBL client initialized")
        print("✓ Reactome client initialized")
        
        # Test URL construction
        from chembio_importer.utils import create_reactome_url
        url = create_reactome_url("R-HSA-198978")
        expected = "https://reactome.org/content/detail/R-HSA-198978"
        assert url == expected, f"Expected {expected}, got {url}"
        print("✓ URL construction works")
        
        return True
        
    except Exception as e:
        print(f"✗ API client test failed: {e}")
        return False

def test_utilities():
    """Test utility functions"""
    print("\nTesting utility functions...")
    
    try:
        from chembio_importer.utils import (
            normalize_activity_value, clean_compound_name, 
            extract_gene_symbol, parse_chembl_activity_relation
        )
        
        # Test activity normalization
        assert normalize_activity_value(100, "μM") == 100000.0  # Convert to nM
        assert normalize_activity_value(50, "nM") == 50.0
        print("✓ Activity normalization works")
        
        # Test name cleaning
        assert clean_compound_name("  Compound Morphine  ") == "Morphine"
        print("✓ Name cleaning works")
        
        # Test gene symbol extraction
        assert extract_gene_symbol("Dopamine D2 receptor (DRD2)") == "DRD2"
        print("✓ Gene symbol extraction works")
        
        # Test relation parsing
        assert parse_chembl_activity_relation("'<'") == "<"
        print("✓ ChEMBL relation parsing works")
        
        return True
        
    except Exception as e:
        print(f"✗ Utility function test failed: {e}")
        return False

def test_configuration():
    """Test configuration loading"""
    print("\nTesting configuration...")
    
    try:
        from chembio_importer import config
        
        # Check required config values exist
        assert hasattr(config, 'CHEMBL_BATCH_SIZE')
        assert hasattr(config, 'REACTOME_BASE_URL')
        assert hasattr(config, 'DATABASE_URL')
        assert hasattr(config, 'SLOW_MODE')
        
        print(f"✓ Configuration loaded:")
        print(f"  - ChEMBL batch size: {config.CHEMBL_BATCH_SIZE}")
        print(f"  - Reactome URL: {config.REACTOME_BASE_URL}")
        print(f"  - Slow mode: {config.SLOW_MODE}")
        
        return True
        
    except Exception as e:
        print(f"✗ Configuration test failed: {e}")
        return False

def test_cli_interface():
    """Test CLI interface"""
    print("\nTesting CLI interface...")
    
    try:
        # Test CLI import
        import subprocess
        import sys
        
        # Test help command
        result = subprocess.run([
            sys.executable, '-m', 'chembio_importer', '--help'
        ], capture_output=True, text=True, cwd=Path(__file__).parent)
        
        if result.returncode == 0:
            print("✓ CLI help command works")
            return True
        else:
            print(f"✗ CLI help failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"✗ CLI test failed: {e}")
        return False

def test_effect_profile_generation():
    """Test effect profile generation"""
    print("\nTesting effect profile generation...")
    
    try:
        from chembio_importer.utils import generate_effect_profile
        
        # Test with mock mechanism data
        mechanisms = [
            {
                'mechanism': 'agonist',
                'target_name': '5HT2A receptor',
                'activity_value': 10.0
            },
            {
                'mechanism': 'antagonist', 
                'target_name': 'dopamine D2 receptor',
                'activity_value': 50.0
            }
        ]
        
        effect_profile = generate_effect_profile(mechanisms)
        print(f"✓ Effect profile generated: {effect_profile}")
        
        return True
        
    except Exception as e:
        print(f"✗ Effect profile test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("ChemBio Importer - Functionality Test")
    print("=" * 50)
    
    # Suppress some logging during tests
    logging.getLogger('chembio_importer').setLevel(logging.WARNING)
    
    tests = [
        test_imports,
        test_configuration,
        test_database_creation,
        test_api_connectivity,
        test_utilities,
        test_effect_profile_generation,
        test_cli_interface,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
    
    print(f"\n{'='*50}")
    print(f"Tests completed: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All tests passed! The ChemBio Importer is ready to use.")
        print("\nNext steps:")
        print("1. Initialize database: python -m chembio_importer --init-db")
        print("2. Import sample data: python -m chembio_importer --from-chembl --limit 10 --slow")
        print("3. Check results: python -m chembio_importer --stats")
    else:
        print(f"❌ {total - passed} tests failed. Please check the installation.")
        sys.exit(1)

if __name__ == "__main__":
    main()
