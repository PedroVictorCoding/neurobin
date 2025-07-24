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

## 🔗 Related Documentation

- **[API Documentation](API_DOCUMENTATION.md)** - Complete REST API reference
- **[Admin Access Guide](ADMIN_ACCESS.md)** - Administrative features
- **[Database Schema](DATABASE_SCHEMA.md)** - Data model documentation
- **[Deployment Guide](DEPLOYMENT.md)** - Production setup instructions
- **[Development Guide](DEVELOPMENT.md)** - Development workflow and standards
- **[Features Documentation](FEATURES.md)** - Complete feature overview
- **[Security Guide](SECURITY.md)** - Security implementation details

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
