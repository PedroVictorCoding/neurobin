# Neurobin - Neurochemical Compound Database Platform

**Version:** 1.0  
**Website:** neurob.in  
**Tech Stack:** Django 5.2.4 + Django Templates + SQLite Database

## 🧠 Project Overview

Neurobin is a comprehensive platform for cataloging, researching, and analyzing neurochemical compounds. It provides tools for compound management, research documentation, user logs, interaction tracking, and community-driven content validation.

### Key Features

- **🔬 Compound Database:** Comprehensive neurochemical compound cataloging with SMILES notation, mechanisms of action, and effect profiles
- **📊 Research Snippets:** Community-driven research documentation with peer review system
- **📝 Intake Logging:** Personal compound intake tracking with analytics dashboard  
- **🔗 Interaction System:** Drug-drug interaction mapping via shared molecular targets
- **👥 User Management:** Account system with profiles, ratings, and role-based permissions
- **⚡ Change Requests:** Collaborative compound editing with approval workflow
- **🎯 Effect Windows:** Detailed pharmacokinetic modeling and visualization

## 🏗️ Architecture

### Backend (Django)
- **Framework:** Django 5.2.4 with REST Framework
- **Database:** SQLite (development) 
- **Templates:** Django template system with Bootstrap 5
- **Apps Structure:**
  - `compounds/` - Core compound data and interactions
  - `research/` - Research snippets and community reviews
  - `logs/` - User intake tracking and analytics
  - `accounts/` - User profiles and authentication
  - `change_requests/` - Collaborative editing system
  - `core/` - Project settings and shared utilities

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Git

### Backend Setup
```bash
cd core/
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:9000
```

> 📚 **For detailed setup instructions, see our [Quick Start Guide](documentation/setup/QUICKSTART.md)**

### Access Points
- **Backend Admin:** http://localhost:9000/admin/
- **API Documentation:** http://localhost:9000/api/
- **Web Interface:** http://localhost:9000/

## 📁 Project Structure

```
neurobin/
├── core/                           # Django application
│   ├── manage.py                   # Django management
│   ├── core/                       # Main project settings
│   │   ├── settings.py            # Django configuration
│   │   ├── urls.py                # URL routing
│   │   └── wsgi.py                # WSGI application
│   ├── compounds/                  # Compound management app
│   │   ├── models.py              # Database models
│   │   ├── api_views.py           # REST API endpoints
│   │   ├── views.py               # Django views
│   │   ├── admin.py               # Admin interface
│   │   └── serializers.py         # API serializers
│   ├── research/                   # Research snippets app
│   ├── logs/                       # User logging app
│   ├── accounts/                   # User management app
│   ├── change_requests/            # Change management app
│   ├── templates/                  # HTML templates
│   │   ├── base.html              # Base template
│   │   ├── compounds/             # Compound templates
│   │   ├── research/              # Research templates
│   │   └── accounts/              # Account templates
│   ├── static/                     # Static assets
│   │   ├── css/                   # Stylesheets
│   │   ├── js/                    # JavaScript files
│   │   └── images/                # Images
│   ├── media/                      # User uploads
│   └── fixtures/                   # Test data
└── docs/                          # Documentation
    ├── API_DOCUMENTATION.md       # API reference
    ├── DATABASE_SCHEMA.md         # Data model documentation
    ├── DEPLOYMENT.md              # Production setup instructions
    ├── DEVELOPMENT.md             # Development guide
    ├── FEATURES.md                # Feature documentation
    ├── SECURITY.md                # Security guide
    └── ADMIN_ACCESS.md            # Admin guide
```

## � Documentation

Comprehensive documentation is available in the [`documentation/`](documentation/) folder:

- **[📚 Documentation Portal](documentation/README.md)** - Main documentation hub
- **[⚡ Quick Start](documentation/setup/QUICKSTART.md)** - Get running in 5 minutes
- **[🔧 Installation Guide](documentation/setup/INSTALLATION.md)** - Complete setup instructions
- **[🧬 ChEMBL Import Guide](documentation/guides/CHEMBL_IMPORT_GUIDE.md)** - Import pharmaceutical data
- **[🔌 API Documentation](documentation/api/API_DOCUMENTATION.md)** - REST API reference
- **[🏗️ Architecture](documentation/technical/architecture.md)** - Technical architecture
- **[🚀 Deployment](documentation/setup/DEPLOYMENT.md)** - Production deployment
- **[👨‍💻 Development](documentation/development/DEVELOPMENT.md)** - Development workflow

### Quick Links
| Topic | Link |
|-------|------|
| Getting Started | [Quick Start Guide](documentation/setup/QUICKSTART.md) |
| API Usage | [API Documentation](documentation/api/API_DOCUMENTATION.md) |
| Data Import | [ChEMBL Import System](documentation/guides/CHEMBL_IMPORT_GUIDE.md) |
| Technical Details | [Architecture Guide](documentation/technical/architecture.md) |

## �🔗 Related Documentation

## 🔗 Legacy Documentation

The following documentation files are being moved to the new structure:

- **[API Documentation](API_DOCUMENTATION.md)** → [New API Docs](documentation/api/API_DOCUMENTATION.md)
- **[Admin Access Guide](ADMIN_ACCESS.md)** → [New Admin Guide](documentation/guides/ADMIN_ACCESS.md)
- **[Database Schema](DATABASE_SCHEMA.md)** → [New Schema Docs](documentation/technical/DATABASE_SCHEMA.md)
- **[Deployment Guide](DEPLOYMENT.md)** → [New Deployment Guide](documentation/setup/DEPLOYMENT.md)
- **[Development Guide](DEVELOPMENT.md)** → [New Dev Guide](documentation/development/DEVELOPMENT.md)
- **[Features Documentation](FEATURES.md)** → [New Features Guide](documentation/guides/FEATURES.md)
- **[Security Guide](SECURITY.md)** → [New Security Guide](documentation/technical/SECURITY.md)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support, please create an issue on GitHub or contact the development team.

---

**Last Updated:** July 2025  
**Maintainers:** Neurobin Development Team
