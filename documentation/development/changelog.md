# Changelog

All notable changes to the Neurobin platform are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive documentation reorganization
- Technical architecture documentation
- Implementation notes and development guides

### Changed
- Moved all documentation to `documentation/` folder
- Improved documentation structure and navigation

## [1.2.0] - 2025-07-24

### Added
- **ChEMBL Import Enhancement**: `--no-limit` flag to bypass compound limits
- **ChEMBL Import Enhancement**: `--skip-existing` flag to skip already imported compounds
- **Target Blacklisting**: Advanced filtering system for excluding unwanted targets
- **Phase Filtering**: Clinical trial phase-based compound filtering (phases 1-4)
- **Expanded Compound Database**: 49+ pharmaceutical compounds for comprehensive imports

### Enhanced
- ChEMBL import system with improved error handling
- Compound name normalization with smart capitalization
- Target organism filtering with case-insensitive partial matching
- Batch processing with progress tracking and status messages

### Fixed
- Target duplication issues in ChEMBL imports
- Compound name inconsistencies
- API timeout handling for large imports

### Technical
- Updated method signatures for skip_existing parameter support
- Enhanced compound existence checking for efficient duplicate prevention
- Improved logging and user feedback during import operations

## [1.1.0] - 2025-07-20

### Added
- **Advanced ChEMBL Integration**: Complete compound-target interaction import system
- **Target Blacklisting System**: Filter out unwanted organisms and targets
- **Phase Filtering**: Import compounds based on clinical trial phases
- **Name-Based Search**: Search and import compounds by name from ChEMBL
- **Compound Categories**: Automatic categorization based on therapeutic indications
- **Interaction Predictions**: Compound-to-compound interaction calculations

### Enhanced
- ChEMBL API integration with comprehensive error handling
- Compound name normalization and smart capitalization
- Target type standardization and organism filtering
- Batch processing with configurable batch sizes and delays

### Fixed
- Memory optimization for large data imports
- API rate limiting compliance with ChEMBL guidelines
- Database constraint handling for duplicate entries

### Technical
- Implemented ChEMBLImporter service class
- Added comprehensive management command system
- Enhanced database schema for ChEMBL data integration
- Improved error handling and user feedback

## [1.0.0] - 2025-07-15

### Added
- **Core Platform**: Initial release of Neurobin neurochemical database platform
- **Compound Database**: Comprehensive compound cataloging with SMILES notation
- **Research System**: Community-driven research documentation with peer review
- **User Management**: Account system with profiles and role-based permissions
- **Intake Logging**: Personal compound intake tracking with analytics
- **Admin Interface**: Django admin interface for platform management

### Features
- Django 5.2.4 backend with REST API
- SQLite database with migration system
- Bootstrap 5 responsive frontend
- JWT authentication system
- CRUD operations for all core models

### Models
- `Compound`: Core compound data with chemical properties
- `Target`: Molecular targets for compound interactions
- `CompoundTargetInteraction`: Compound-target relationship mapping
- `ResearchSnippet`: Community research documentation
- `IntakeLog`: User intake tracking and analytics
- `Profile`: Extended user profile information

### API Endpoints
- Compounds API with search and filtering
- Research snippets API with review system
- User profile and authentication APIs
- Admin APIs for platform management

## [0.9.0] - 2025-07-10 - Pre-release

### Added
- Project initialization and structure setup
- Database schema design and migrations
- Basic Django application framework
- Core model definitions
- Initial admin interface setup

### Technical
- Django project configuration
- PostgreSQL database integration
- Static file handling setup
- Basic URL routing structure

---

## Release Notes

### Version 1.2.0 Highlights

This release significantly enhances the ChEMBL import system with advanced filtering and operational control features:

#### 🚀 New Import Flags
- **`--no-limit`**: Import comprehensive pharmaceutical compound sets without artificial limits
- **`--skip-existing`**: Efficiently skip compounds already in the database
- **Enhanced filtering**: Combine multiple filters for precise data imports

#### 🎯 Improved User Experience
- Clear status messages for skipped compounds
- Progress tracking for large imports
- Better error handling and user feedback

#### 📊 Database Expansion
- Support for importing 49+ diverse pharmaceutical compounds
- Includes cardiovascular drugs, antibiotics, neurological medications, cancer therapeutics
- Comprehensive compound coverage across therapeutic categories

### Version 1.1.0 Highlights

This release introduces comprehensive ChEMBL integration:

#### 🔬 ChEMBL API Integration
- Direct import from ChEMBL's official API
- Comprehensive compound-target interaction data
- Automatic target and mechanism processing

#### 🎯 Advanced Filtering
- Target blacklisting for organism exclusion
- Clinical trial phase filtering (1-4)
- Name-based compound search and import

#### 🏗️ Enhanced Architecture
- Service-oriented design patterns
- Comprehensive error handling
- Scalable batch processing system

### Version 1.0.0 Highlights

The initial release provides a solid foundation:

#### 🧠 Core Platform
- Complete neurochemical compound database
- Community-driven research system
- User intake tracking and analytics

#### 🔧 Technical Foundation
- Modern Django 5.2.4 framework
- RESTful API architecture
- Responsive Bootstrap 5 frontend

#### 🛡️ Security & Quality
- JWT authentication system
- Comprehensive input validation
- Role-based access control

## Migration Guide

### Upgrading to 1.2.0

No database migrations required. New flags are backward compatible.

```bash
# Update codebase
git pull origin main

# Install any new dependencies
pip install -r requirements.txt

# Test new import flags
python manage.py import_chembl_interactions --compounds CHEMBL25 --skip-existing
```

### Upgrading to 1.1.0

Database migrations required for ChEMBL integration:

```bash
# Update codebase
git pull origin main

# Install dependencies
pip install -r requirements.txt

# Apply migrations
python manage.py migrate

# Test ChEMBL import
python manage.py import_chembl_interactions --compounds CHEMBL25
```

### Upgrading to 1.0.0

Initial installation - see [Installation Guide](../setup/INSTALLATION.md).

## Contributors

- **PedroVictorCoding** - Platform architect and lead developer
- **Community Contributors** - Feature requests and testing

## Support

- **Issues**: [GitHub Issues](https://github.com/PedroVictorCoding/neurobin/issues)
- **Documentation**: [Documentation Portal](../README.md)
- **Discussions**: [GitHub Discussions](https://github.com/PedroVictorCoding/neurobin/discussions)

---
*For detailed technical changes, see [Implementation Notes](./implementation-notes.md)*
