# Installation Guide

Complete installation instructions for the Neurobin platform.

## 📋 System Requirements

### Minimum Requirements
- **Python**: 3.11 or higher
- **Memory**: 2GB RAM
- **Storage**: 1GB free space
- **Operating System**: Linux, macOS, or Windows

### Recommended Requirements
- **Python**: 3.12+
- **Memory**: 4GB RAM
- **Storage**: 5GB free space
- **Database**: PostgreSQL (production)
- **Web Server**: Nginx + Gunicorn (production)

## 🔧 Development Installation

### 1. System Dependencies

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip git
```

#### macOS
```bash
# Install Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python and Git
brew install python@3.11 git
```

#### Windows
1. Download Python 3.11+ from [python.org](https://python.org)
2. Install Git from [git-scm.com](https://git-scm.com)
3. Ensure Python and Git are in your PATH

### 2. Project Setup

#### Clone Repository
```bash
git clone https://github.com/PedroVictorCoding/neurobin.git
cd neurobin
```

#### Create Virtual Environment
```bash
cd core/
python3.11 -m venv venv

# Activate virtual environment
# Linux/macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

#### Install Python Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Database Setup

#### SQLite (Development)
```bash
# Apply migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Load sample data (optional)
python manage.py loaddata fixtures/sample_data.json
```

#### PostgreSQL (Production)
```bash
# Install PostgreSQL
sudo apt install postgresql postgresql-contrib  # Ubuntu/Debian
brew install postgresql  # macOS

# Create database and user
sudo -u postgres psql
CREATE DATABASE neurobin;
CREATE USER neurobin_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE neurobin TO neurobin_user;
\q

# Update settings.py for PostgreSQL
# See configuration section below
```

### 4. Environment Configuration

Create `.env` file in `core/` directory:
```env
# Debug mode (set to False in production)
DEBUG=True

# Secret key (generate a new one for production)
SECRET_KEY=your-very-secret-key-here

# Database configuration
DATABASE_URL=sqlite:///db.sqlite3
# For PostgreSQL: DATABASE_URL=postgresql://user:password@localhost:5432/neurobin

# Allowed hosts
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Static files
STATIC_URL=/static/
STATIC_ROOT=/path/to/static/files/

# Media files
MEDIA_URL=/media/
MEDIA_ROOT=/path/to/media/files/

# Email configuration (optional)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password

# ChEMBL API settings
CHEMBL_API_BASE_URL=https://www.ebi.ac.uk/chembl/api/data
CHEMBL_REQUEST_TIMEOUT=30
```

### 5. Static Files and Media

```bash
# Collect static files
python manage.py collectstatic --noinput

# Create media directories
mkdir -p media/profile_images
mkdir -p media/compound_images
```

### 6. Development Server

```bash
# Start development server
python manage.py runserver 0.0.0.0:9000

# Or with specific settings
python manage.py runserver --settings=core.settings.development
```

## 🚀 Production Installation

### 1. Server Preparation

#### Ubuntu Server Setup
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install system dependencies
sudo apt install python3.11 python3.11-venv python3-pip git nginx postgresql postgresql-contrib redis-server supervisor curl

# Create application user
sudo adduser neurobin
sudo usermod -aG sudo neurobin
```

### 2. Application Deployment

```bash
# Switch to application user
sudo su - neurobin

# Clone repository
git clone https://github.com/PedroVictorCoding/neurobin.git /home/neurobin/neurobin
cd /home/neurobin/neurobin/core

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn psycopg2-binary
```

### 3. Database Configuration

```bash
# Create PostgreSQL database
sudo -u postgres psql
CREATE DATABASE neurobin_prod;
CREATE USER neurobin_user WITH PASSWORD 'secure_password';
ALTER ROLE neurobin_user SET client_encoding TO 'utf8';
ALTER ROLE neurobin_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE neurobin_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE neurobin_prod TO neurobin_user;
\q
```

### 4. Production Settings

Create `/home/neurobin/neurobin/core/.env`:
```env
DEBUG=False
SECRET_KEY=very-secure-secret-key-for-production
DATABASE_URL=postgresql://neurobin_user:secure_password@localhost:5432/neurobin_prod
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
STATIC_ROOT=/home/neurobin/neurobin/static/
MEDIA_ROOT=/home/neurobin/neurobin/media/
```

### 5. Web Server Configuration

#### Gunicorn Service
Create `/etc/systemd/system/neurobin.service`:
```ini
[Unit]
Description=Neurobin Django Application
After=network.target

[Service]
User=neurobin
Group=www-data
WorkingDirectory=/home/neurobin/neurobin/core
Environment="PATH=/home/neurobin/neurobin/core/venv/bin"
ExecStart=/home/neurobin/neurobin/core/venv/bin/gunicorn --workers 3 --bind unix:/home/neurobin/neurobin/neurobin.sock core.wsgi:application
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

#### Nginx Configuration
Create `/etc/nginx/sites-available/neurobin`:
```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    location = /favicon.ico { access_log off; log_not_found off; }
    
    location /static/ {
        root /home/neurobin/neurobin;
    }

    location /media/ {
        root /home/neurobin/neurobin;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/home/neurobin/neurobin/neurobin.sock;
    }
}
```

### 6. SSL Configuration (Recommended)

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx

# Obtain SSL certificate
sudo certbot --nginx -d your-domain.com -d www.your-domain.com

# Test auto-renewal
sudo certbot renew --dry-run
```

### 7. Start Services

```bash
# Enable and start services
sudo systemctl enable neurobin
sudo systemctl start neurobin
sudo systemctl enable nginx
sudo systemctl start nginx

# Check status
sudo systemctl status neurobin
sudo systemctl status nginx
```

## 🔧 Configuration Options

### Django Settings

#### Development Settings
Located in `core/settings.py`:
- DEBUG mode enabled
- SQLite database
- Development middleware
- Detailed error pages

#### Production Settings
Create `core/settings/production.py`:
```python
from .base import *

DEBUG = False
ALLOWED_HOSTS = ['your-domain.com']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'neurobin_prod',
        'USER': 'neurobin_user',
        'PASSWORD': 'secure_password',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}

STATIC_ROOT = '/home/neurobin/neurobin/static/'
MEDIA_ROOT = '/home/neurobin/neurobin/media/'
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `True` |
| `SECRET_KEY` | Django secret key | Required |
| `DATABASE_URL` | Database connection string | SQLite |
| `ALLOWED_HOSTS` | Allowed host names | `localhost` |
| `STATIC_ROOT` | Static files directory | `staticfiles/` |
| `MEDIA_ROOT` | Media files directory | `media/` |

## 🧪 Testing Installation

### Run Tests
```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test compounds

# Run with coverage
pip install coverage
coverage run --source='.' manage.py test
coverage report
```

### Health Check
```bash
# Check system status
python manage.py check

# Check database connectivity
python manage.py shell -c "from django.db import connection; connection.ensure_connection(); print('Database OK')"

# Test ChEMBL API connection
python manage.py shell -c "from compounds.chembl_importer import ChEMBLImporter; importer = ChEMBLImporter(); print('ChEMBL API OK' if importer.test_connection() else 'ChEMBL API Failed')"
```

## 🔍 Troubleshooting

### Common Issues

#### Permission Errors
```bash
# Fix file permissions
sudo chown -R neurobin:www-data /home/neurobin/neurobin
sudo chmod -R 755 /home/neurobin/neurobin
```

#### Database Connection Issues
```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Test database connection
sudo -u postgres psql -d neurobin_prod -c "SELECT 1;"
```

#### Static Files Not Loading
```bash
# Collect static files
python manage.py collectstatic --noinput

# Check Nginx configuration
sudo nginx -t
sudo systemctl reload nginx
```

#### Import Errors
```bash
# Verify Python path
echo $PYTHONPATH

# Check virtual environment
which python
pip list
```

## 📚 Additional Resources

- [Deployment Guide](./DEPLOYMENT.md) - Production deployment details
- [Development Guide](../development/DEVELOPMENT.md) - Development workflow
- [Security Guide](../technical/SECURITY.md) - Security best practices
- [API Documentation](../api/API_DOCUMENTATION.md) - API reference

---
*For quick setup, see the [Quick Start Guide](./QUICKSTART.md)*
