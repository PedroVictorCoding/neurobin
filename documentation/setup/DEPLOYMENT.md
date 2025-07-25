# Neurobin Deployment Guide

## Overview

This guide covers deploying the Neurobin platform to production environments. The platform consists of a Django application with REST API and Django template-based frontend.

## Production Architecture

```
[Internet] → [Reverse Proxy] → [Django App] → [Database]
                ↓
          [Static Files CDN]
```

## Prerequisites

### System Requirements
- **OS:** Ubuntu 20.04+ / CentOS 8+ / Docker
- **Python:** 3.11+
- **Database:** PostgreSQL 14+ (production) / SQLite (development)
- **Web Server:** Nginx
- **Process Manager:** Gunicorn + Supervisor
- **SSL:** Let's Encrypt / Custom certificate

### Domain & DNS
- Domain name pointing to server IP
- SSL certificate for HTTPS
- CDN setup for static assets (optional)

## Database Setup

### PostgreSQL Production Database

```bash
# Install PostgreSQL
sudo apt update
sudo apt install postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql
CREATE DATABASE neurobin_db;
CREATE USER neurobin_user WITH PASSWORD 'secure_password_here';
GRANT ALL PRIVILEGES ON DATABASE neurobin_db TO neurobin_user;
ALTER USER neurobin_user CREATEDB;
\q
```

### Environment Variables

Create `/opt/neurobin/.env`:
```bash
# Django Settings
DEBUG=False
SECRET_KEY=your_super_secret_key_here_minimum_50_characters_long
ALLOWED_HOSTS=neurob.in,www.neurob.in,your-domain.com

# Database
DATABASE_URL=postgresql://neurobin_user:secure_password_here@localhost:5432/neurobin_db

# Email (for password resets)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=noreply@neurob.in
EMAIL_HOST_PASSWORD=app_specific_password
EMAIL_USE_TLS=True

# Security
SECURE_SSL_REDIRECT=True
SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# API Keys (if needed)
OPENAI_API_KEY=your_openai_key_here
```

## Backend Deployment

### 1. Application Setup

```bash
# Create application directory
sudo mkdir -p /opt/neurobin
sudo chown $USER:$USER /opt/neurobin
cd /opt/neurobin

```bash
# Clone repository
git clone <repository-url>
cd neurobin

# Setup Python environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure database
python core/manage.py migrate
python core/manage.py createsuperuser

# Collect static files
python core/manage.py collectstatic

# Test deployment
python core/manage.py runserver
```
```

### 2. Gunicorn Configuration

Create `/opt/neurobin/gunicorn.conf.py`:
```python
# Gunicorn configuration file
import multiprocessing

# Server socket
bind = "127.0.0.1:8000"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 30
keepalive = 2

# Restart workers after this many requests, to prevent memory leaks
max_requests = 1000
max_requests_jitter = 50

# Process naming
proc_name = 'neurobin'

# Logging
accesslog = '/var/log/neurobin/access.log'
errorlog = '/var/log/neurobin/error.log'
loglevel = 'info'

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Performance
preload_app = True
```

### 3. Systemd Service

Create `/etc/systemd/system/neurobin.service`:
```ini
[Unit]
Description=Neurobin Django Application
After=network.target

[Service]
Type=notify
User=www-data
Group=www-data
RuntimeDirectory=neurobin
WorkingDirectory=/opt/neurobin/core
Environment=DJANGO_SETTINGS_MODULE=core.settings
EnvironmentFile=/opt/neurobin/.env
ExecStart=/opt/neurobin/venv/bin/gunicorn --config /opt/neurobin/gunicorn.conf.py core.wsgi:application
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 4. Start Backend Services

```bash
# Create log directory
sudo mkdir -p /var/log/neurobin
sudo chown www-data:www-data /var/log/neurobin

# Change ownership
sudo chown -R www-data:www-data /opt/neurobin

# Enable and start service
sudo systemctl enable neurobin
sudo systemctl start neurobin
sudo systemctl status neurobin
```

## Frontend Deployment

Since the platform uses Django templates, static files are served directly by Django and collected using `collectstatic`. No separate frontend build process is required.

## Web Server Configuration

### Nginx Setup

Install Nginx:
```bash
sudo apt install nginx
```

Create `/etc/nginx/sites-available/neurobin`:
```nginx
# Upstream Django application
upstream django_app {
    server 127.0.0.1:8000;
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name neurob.in www.neurob.in;
    return 301 https://$server_name$request_uri;
}

# Main HTTPS server
server {
    listen 443 ssl http2;
    server_name neurob.in www.neurob.in;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/neurob.in/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/neurob.in/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;

    # Security Headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' https://fonts.gstatic.com;" always;

    # Gzip Compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1000;
    gzip_types application/json application/javascript text/css text/javascript application/wasm;

    # Rate Limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=login:10m rate=1r/s;

    # Django Application
    location / {
        proxy_pass http://django_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }

    # Django Static Files
    location /static/ {
        alias /opt/neurobin/core/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Django Media Files
    location /media/ {
        alias /opt/neurobin/core/media/;
        expires 1y;
        add_header Cache-Control "public";
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/neurobin /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## SSL Certificate

### Let's Encrypt Setup

```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d neurob.in -d www.neurob.in

# Test auto-renewal
sudo certbot renew --dry-run
```

## Monitoring & Logging

### 1. Log Rotation

Create `/etc/logrotate.d/neurobin`:
```
/var/log/neurobin/*.log {
    daily
    missingok
    rotate 52
    compress
    delaycompress
    notifempty
    create 0644 www-data www-data
    postrotate
        systemctl reload neurobin
    endscript
}
```

### 2. Health Check Script

Create `/opt/neurobin/health_check.py`:
```python
#!/usr/bin/env python3
import requests
import sys
import os

def check_health():
    try:
        # Check Django API
        response = requests.get('https://neurob.in/api/health/', timeout=5)
        if response.status_code != 200:
            return False, f"API health check failed: {response.status_code}"
        
        # Check database connectivity
        response = requests.get('https://neurob.in/api/compounds/compoundcategories/', timeout=5)
        if response.status_code != 200:
            return False, f"Database connectivity failed: {response.status_code}"
        
        return True, "All systems operational"
    
    except Exception as e:
        return False, f"Health check error: {str(e)}"

if __name__ == "__main__":
    healthy, message = check_health()
    print(message)
    sys.exit(0 if healthy else 1)
```

### 3. Monitoring with Supervisor

Install supervisor:
```bash
sudo apt install supervisor
```

Create `/etc/supervisor/conf.d/neurobin-monitor.conf`:
```ini
[program:neurobin-health]
command=/opt/neurobin/venv/bin/python /opt/neurobin/health_check.py
directory=/opt/neurobin
user=www-data
autostart=true
autorestart=true
startretries=3
redirect_stderr=true
stdout_logfile=/var/log/neurobin/health.log
```

## Backup Strategy

### 1. Database Backup Script

Create `/opt/neurobin/backup.sh`:
```bash
#!/bin/bash

BACKUP_DIR="/opt/backups/neurobin"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_NAME="neurobin_db"

# Create backup directory
mkdir -p $BACKUP_DIR

# Database backup
pg_dump $DB_NAME | gzip > $BACKUP_DIR/db_backup_$TIMESTAMP.sql.gz

# Media files backup
tar -czf $BACKUP_DIR/media_backup_$TIMESTAMP.tar.gz /opt/neurobin/core/media/

# Keep only last 30 days of backups
find $BACKUP_DIR -name "*.gz" -mtime +30 -delete

echo "Backup completed: $TIMESTAMP"
```

### 2. Automated Backups

Add to crontab:
```bash
# Daily backup at 2 AM
0 2 * * * /opt/neurobin/backup.sh
```

## Performance Optimization

### 1. Database Optimization

```sql
-- Add indexes for common queries
CREATE INDEX CONCURRENTLY idx_research_snippet_compound_status 
ON research_researchsnippet(compound_id, status);

CREATE INDEX CONCURRENTLY idx_logs_user_date 
ON logs_intakelog(user_id, taken_at DESC);

-- Analyze tables
ANALYZE;
```

### 2. Django Settings

Update `core/settings.py` for production:
```python
# Cache configuration
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
    }
}

# Session configuration
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# Database connection pooling
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'OPTIONS': {
            'MAX_CONNS': 20,
            'conn_max_age': 0,
        },
    }
}
```

## Security Checklist

- [ ] SSL/TLS encryption enabled
- [ ] Security headers configured
- [ ] Rate limiting implemented
- [ ] Database credentials secured
- [ ] Debug mode disabled
- [ ] Secret key rotated
- [ ] File permissions restricted
- [ ] Firewall configured
- [ ] Regular security updates
- [ ] Backup encryption enabled

## Troubleshooting

### Common Issues

1. **502 Bad Gateway**
   ```bash
   sudo systemctl status neurobin
   sudo journalctl -u neurobin -f
   ```

2. **Static Files Not Loading**
   ```bash
   python manage.py collectstatic --noinput
   sudo nginx -t
   ```

3. **Database Connection Issues**
   ```bash
   sudo -u postgres psql -c "\l"
   python manage.py dbshell
   ```

4. **SSL Certificate Problems**
   ```bash
   sudo certbot certificates
   sudo certbot renew
   ```

### Logs Locations
- Nginx: `/var/log/nginx/`
- Django: `/var/log/neurobin/`
- System: `journalctl -u neurobin`

## Scaling Considerations

### Horizontal Scaling
- Load balancer (HAProxy/AWS ALB)
- Multiple Django instances
- Database read replicas
- Redis cluster for caching
- CDN for static assets

### Vertical Scaling
- Increase server resources
- Database optimization
- Connection pooling
- Query optimization

---

**Deployment Version:** 1.0  
**Last Updated:** July 2025  
**Environment:** Production Ready
