# Neurobin Security Guide

## Overview

This document outlines the comprehensive security measures implemented in the Neurobin platform, covering data protection, access control, input validation, and operational security practices.

## Security Architecture

### Multi-Layer Security Model
```
┌─────────────────────────────────────────┐
│             Application Layer           │
├─────────────────────────────────────────┤
│              API Security               │
├─────────────────────────────────────────┤
│            Authentication               │
├─────────────────────────────────────────┤
│             Authorization               │
├─────────────────────────────────────────┤
│             Data Validation             │
├─────────────────────────────────────────┤
│            Database Security            │
├─────────────────────────────────────────┤
│            Network Security             │
└─────────────────────────────────────────┘
```

## Authentication & Authorization

### User Authentication

#### JWT Token System
```python
# JWT Configuration
JWT_AUTH = {
    'JWT_SECRET_KEY': settings.SECRET_KEY,
    'JWT_ALGORITHM': 'HS256',
    'JWT_EXPIRATION_DELTA': timedelta(hours=24),
    'JWT_REFRESH_EXPIRATION_DELTA': timedelta(days=7),
    'JWT_ALLOW_REFRESH': True,
}
```

#### Password Security
- **Minimum Requirements:**
  - 8+ characters length
  - Mixed case letters
  - Numbers and special characters
  - No common passwords (Django's password validation)

- **Hashing Algorithm:** PBKDF2 with SHA256 (Django default)
- **Salt:** Unique per password
- **Iteration Count:** 390,000+ (configurable)

#### Session Security
```python
# Session Configuration
SESSION_COOKIE_SECURE = True      # HTTPS only
SESSION_COOKIE_HTTPONLY = True    # No JavaScript access
SESSION_COOKIE_SAMESITE = 'Strict'  # CSRF protection
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 86400        # 24 hours
```

### Role-Based Access Control (RBAC)

#### User Roles
1. **Anonymous Users**
   - Read-only access to public compounds
   - No research snippet access
   - No personal data tracking

2. **Authenticated Users**
   - Full compound database access
   - Personal intake logging
   - Research snippet submission
   - Rating and review capabilities

3. **Trusted Reviewers**
   - Enhanced voting weight (configurable)
   - Access to review moderation tools
   - Priority in review queues

4. **Moderators**
   - Content moderation capabilities
   - User management (limited)
   - Research snippet validation
   - Flag resolution authority

5. **Administrators**
   - Full system access
   - User management
   - System configuration
   - Data export/import

#### Permission Matrix
```python
# permissions.py
class CompoundPermissions(BasePermission):
    def has_permission(self, request, view):
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return True  # Read access for all
        return request.user.is_authenticated  # Write requires auth
    
    def has_object_permission(self, request, view, obj):
        if request.method in ['GET', 'HEAD', 'OPTIONS']:
            return True
        return (request.user.is_staff or 
                obj.created_by == request.user)
```

## Input Validation & Sanitization

### Server-Side Validation

#### Django Form Validation
```python
# forms.py
class CompoundForm(forms.ModelForm):
    class Meta:
        model = Compound
        fields = ['name', 'description', 'smiles']
    
    def clean_name(self):
        name = self.cleaned_data['name']
        if len(name) < 2:
            raise ValidationError("Name must be at least 2 characters")
        # Sanitize HTML and potentially harmful content
        name = bleach.clean(name, strip=True)
        return name
    
    def clean_smiles(self):
        smiles = self.cleaned_data.get('smiles', '')
        if smiles:
            # Validate SMILES notation
            if not self.is_valid_smiles(smiles):
                raise ValidationError("Invalid SMILES notation")
        return smiles
```

#### API Input Validation
```python
# serializers.py
class CompoundSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=500,
        validators=[
            MinLengthValidator(2),
            RegexValidator(
                regex=r'^[a-zA-Z0-9\s\-\(\)]+$',
                message='Name contains invalid characters'
            )
        ]
    )
    
    def validate_description(self, value):
        # HTML sanitization
        cleaned_description = bleach.clean(
            value,
            tags=['p', 'br', 'strong', 'em'],
            strip=True
        )
        return cleaned_description
```

### Client-Side Validation

#### React Form Validation
```jsx
// CompoundForm.jsx
const validateCompound = (data) => {
  const errors = {};
  
  // Name validation
  if (!data.name || data.name.length < 2) {
    errors.name = 'Name must be at least 2 characters';
  }
  
  // SMILES validation
  if (data.smiles && !isValidSMILES(data.smiles)) {
    errors.smiles = 'Invalid SMILES notation';
  }
  
  // XSS prevention - strip HTML
  if (data.description) {
    data.description = DOMPurify.sanitize(data.description);
  }
  
  return errors;
};
```

## Cross-Site Security

### CSRF Protection

#### Django CSRF Middleware
```python
# settings.py
MIDDLEWARE = [
    'django.middleware.csrf.CsrfViewMiddleware',
    # ... other middleware
]

CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = 'Strict'
CSRF_TRUSTED_ORIGINS = ['https://neurob.in']
```

#### API CSRF Handling
```javascript
// apiService.js
const getCsrfToken = () => {
  return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
         document.querySelector('meta[name=csrf-token]')?.getAttribute('content');
};

axios.defaults.headers.common['X-CSRFToken'] = getCsrfToken();
```

### XSS Prevention

#### Content Security Policy (CSP)
```nginx
# nginx.conf
add_header Content-Security-Policy "
    default-src 'self';
    script-src 'self' 'unsafe-inline' 'unsafe-eval';
    style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
    img-src 'self' data: https:;
    font-src 'self' https://fonts.gstatic.com;
    connect-src 'self' https://api.neurob.in;
    frame-ancestors 'none';
" always;
```

#### HTML Sanitization
```python
# utils.py
import bleach

ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'blockquote']
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title'],
    'abbr': ['title'],
    'acronym': ['title'],
}

def sanitize_html(content):
    return bleach.clean(
        content,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True
    )
```

## Data Protection

### Personal Data Handling

#### Data Minimization
- Collect only necessary user information
- Optional fields clearly marked
- Regular data audit and cleanup

#### Data Encryption
```python
# models.py
from django.contrib.auth.hashers import make_password, check_password

class UserProfile(models.Model):
    # Sensitive data encryption
    encrypted_notes = models.TextField(blank=True)
    
    def set_notes(self, notes):
        self.encrypted_notes = make_password(notes)
    
    def check_notes(self, notes):
        return check_password(notes, self.encrypted_notes)
```

#### Data Access Logging
```python
# middleware.py
class DataAccessLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Log sensitive data access
        if '/api/accounts/' in request.path:
            logger.info(f"User data access: {request.user} - {request.path}")
        
        response = self.get_response(request)
        return response
```

### Database Security

#### Connection Security
```python
# settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'OPTIONS': {
            'sslmode': 'require',
            'sslcert': '/path/to/client-cert.pem',
            'sslkey': '/path/to/client-key.pem',
            'sslrootcert': '/path/to/ca-cert.pem',
        },
    }
}
```

#### SQL Injection Prevention
- Django ORM usage (parameterized queries)
- Input validation and sanitization
- Prepared statements for raw SQL

```python
# Secure query example
compounds = Compound.objects.filter(
    name__icontains=user_input  # Automatically escaped
)

# Avoid raw SQL, but if necessary:
compounds = Compound.objects.raw(
    "SELECT * FROM compounds_compound WHERE name LIKE %s",
    ['%' + user_input + '%']  # Parameterized
)
```

## Network Security

### HTTPS Enforcement

#### SSL/TLS Configuration
```nginx
# nginx.conf
server {
    listen 443 ssl http2;
    ssl_certificate /etc/letsencrypt/live/neurob.in/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/neurob.in/privkey.pem;
    
    # Strong SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # HSTS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
}
```

#### Django SSL Settings
```python
# settings.py (production)
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_REFERRER_POLICY = 'same-origin'
```

### Rate Limiting

#### API Rate Limiting
```python
# settings.py
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour'
    }
}
```

#### Nginx Rate Limiting
```nginx
# nginx.conf
http {
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=login:10m rate=1r/s;
    
    server {
        location /api/ {
            limit_req zone=api burst=20 nodelay;
        }
        
        location /accounts/login/ {
            limit_req zone=login burst=5 nodelay;
        }
    }
}
```

## Security Headers

### HTTP Security Headers
```python
# middleware.py
class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Security headers
        response['X-Frame-Options'] = 'DENY'
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'same-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        return response
```

## File Upload Security

### Upload Validation
```python
# validators.py
def validate_file_extension(file):
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif']
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in allowed_extensions:
        raise ValidationError('Invalid file type')

def validate_file_size(file):
    max_size = 5 * 1024 * 1024  # 5MB
    if file.size > max_size:
        raise ValidationError('File too large')

class UserProfile(models.Model):
    profile_image = models.ImageField(
        upload_to='profile_images/',
        validators=[validate_file_extension, validate_file_size]
    )
```

### File Storage Security
```python
# settings.py
import os

# Secure file storage
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
MEDIA_URL = '/media/'

# File serving through Django (development)
if DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

## Error Handling & Logging

### Secure Error Handling
```python
# settings.py (production)
DEBUG = False
ALLOWED_HOSTS = ['neurob.in', 'www.neurob.in']

# Custom error pages
handler404 = 'core.views.error_404'
handler500 = 'core.views.error_500'

# Logging configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'security_file': {
            'level': 'WARNING',
            'class': 'logging.FileHandler',
            'filename': '/var/log/neurobin/security.log',
        },
    },
    'loggers': {
        'security': {
            'handlers': ['security_file'],
            'level': 'WARNING',
            'propagate': True,
        },
    },
}
```

### Security Event Logging
```python
# security_logger.py
import logging

security_logger = logging.getLogger('security')

def log_failed_login(username, ip_address):
    security_logger.warning(
        f"Failed login attempt - Username: {username}, IP: {ip_address}"
    )

def log_admin_access(user, action, resource):
    security_logger.info(
        f"Admin access - User: {user}, Action: {action}, Resource: {resource}"
    )

def log_suspicious_activity(user, activity, details):
    security_logger.warning(
        f"Suspicious activity - User: {user}, Activity: {activity}, Details: {details}"
    )
```

## Security Monitoring

### Intrusion Detection
```python
# security_middleware.py
class IntrusionDetectionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.suspicious_patterns = [
            r'<script',
            r'javascript:',
            r'SELECT.*FROM',
            r'UNION.*SELECT',
        ]
    
    def __call__(self, request):
        # Check for suspicious patterns
        query_string = request.META.get('QUERY_STRING', '')
        for pattern in self.suspicious_patterns:
            if re.search(pattern, query_string, re.IGNORECASE):
                log_suspicious_activity(
                    request.user,
                    'Potential injection attempt',
                    query_string
                )
                return HttpResponseForbidden('Suspicious activity detected')
        
        return self.get_response(request)
```

### Automated Security Scans
```bash
#!/bin/bash
# security_scan.sh

# Check for security updates
apt list --upgradable | grep -i security

# Check for unusual network connections
netstat -tulpn | grep :8000

# Check for failed login attempts
grep "Failed login" /var/log/neurobin/security.log | tail -20

# Check disk usage (prevent DoS via storage)
df -h | awk '$5 > 80 {print "Warning: " $5 " full on " $6}'
```

## Incident Response

### Security Incident Procedures

#### 1. Detection and Analysis
- Automated monitoring alerts
- User reports and feedback
- Regular security audits
- Log analysis

#### 2. Containment and Eradication
```bash
# Emergency procedures
# 1. Block suspicious IP addresses
iptables -A INPUT -s SUSPICIOUS_IP -j DROP

# 2. Disable compromised user accounts
python manage.py shell -c "
from django.contrib.auth.models import User
User.objects.filter(username='compromised_user').update(is_active=False)
"

# 3. Change critical passwords
# 4. Revoke API tokens
# 5. Update security keys
```

#### 3. Recovery and Lessons Learned
- System restoration from clean backups
- Security patch deployment
- User notification (if required)
- Incident documentation
- Process improvement

### Security Contact Information
- **Security Team:** security@neurob.in
- **Emergency Contact:** +1-XXX-XXX-XXXX
- **PGP Key:** Available on website
- **Response Time:** 24 hours for critical issues

## Compliance & Standards

### Data Protection Compliance
- **GDPR Compliance:** EU data protection regulations
- **CCPA Compliance:** California privacy laws
- **Data Retention Policies:** Automated cleanup procedures
- **User Rights:** Data access, portability, and deletion

### Security Standards
- **OWASP Top 10:** Protection against common vulnerabilities
- **ISO 27001:** Information security management
- **NIST Framework:** Cybersecurity best practices
- **PCI DSS:** Payment card data security (if applicable)

## Security Checklist

### Development Security
- [ ] Input validation on all user inputs
- [ ] Output encoding for all dynamic content
- [ ] Parameterized database queries
- [ ] Secure authentication implementation
- [ ] Proper error handling
- [ ] Security headers configuration
- [ ] HTTPS enforcement
- [ ] Regular dependency updates

### Deployment Security
- [ ] Production environment hardening
- [ ] Firewall configuration
- [ ] SSL/TLS certificate installation
- [ ] Security monitoring setup
- [ ] Backup encryption
- [ ] Access control implementation
- [ ] Log monitoring configuration
- [ ] Incident response plan

### Operational Security
- [ ] Regular security audits
- [ ] Penetration testing
- [ ] Security training for team
- [ ] Password policy enforcement
- [ ] Multi-factor authentication
- [ ] Regular backup testing
- [ ] Security patch management
- [ ] Vulnerability scanning

---

**Security Guide Version:** 1.0  
**Last Updated:** July 2025  
**Classification:** Internal Use  
**Review Cycle:** Quarterly
