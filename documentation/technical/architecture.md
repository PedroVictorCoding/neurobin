# System Architecture

Overview of the Neurobin platform's technical architecture, components, and design patterns.

## 🏗️ High-Level Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │    Backend      │    │   Database      │
│                 │    │                 │    │                 │
│ • React/Vite    │◄──►│ • Django 5.2.4  │◄──►│ • SQLite/       │
│ • Bootstrap 5   │    │ • REST Framework │    │   PostgreSQL    │
│ • JavaScript    │    │ • JWT Auth      │    │ • Redis Cache   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │              ┌─────────────────┐              │
         └──────────────►│  External APIs  │◄─────────────┘
                         │                 │
                         │ • ChEMBL API    │
                         │ • PubChem API   │
                         └─────────────────┘
```

## 🗂️ Application Structure

### Django Apps Organization

```
core/
├── core/                   # Project settings and configuration
│   ├── settings.py        # Main settings
│   ├── urls.py           # Root URL configuration
│   ├── wsgi.py           # WSGI application
│   └── asgi.py           # ASGI application (future WebSocket support)
├── accounts/             # User management and authentication
├── compounds/            # Core compound data and interactions
├── research/             # Research snippets and community reviews
├── logs/                 # User intake tracking and analytics
├── change_requests/      # Collaborative editing system
└── static/              # Static files (CSS, JS, images)
```

### Application Responsibilities

| App | Purpose | Key Models |
|-----|---------|------------|
| `accounts` | User management, profiles, authentication | `User`, `Profile` |
| `compounds` | Compound database, targets, interactions | `Compound`, `Target`, `Interaction` |
| `research` | Community-driven research documentation | `ResearchSnippet`, `Review` |
| `logs` | Intake tracking, analytics, effect windows | `IntakeLog`, `EffectWindow` |
| `change_requests` | Collaborative editing workflow | `ChangeRequest`, `Approval` |

## 🔧 Technology Stack

### Backend Technologies

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| **Framework** | Django | 5.2.4 | Web framework |
| **API** | Django REST Framework | 3.14+ | REST API development |
| **Database** | SQLite/PostgreSQL | Latest | Data persistence |
| **Authentication** | JWT | Latest | API authentication |
| **Cache** | Redis | Latest | Caching and sessions |
| **Task Queue** | Celery | Latest | Background tasks |
| **Web Server** | Gunicorn | Latest | WSGI server |

### Frontend Technologies

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| **Framework** | React | 18+ | UI framework |
| **Build Tool** | Vite | Latest | Build and development |
| **Styling** | Bootstrap | 5.x | CSS framework |
| **State Management** | Context API | Built-in | State management |
| **HTTP Client** | Axios | Latest | API communication |

### External Services

| Service | Purpose | Integration |
|---------|---------|-------------|
| **ChEMBL API** | Pharmaceutical data | REST API |
| **PubChem API** | Chemical information | REST API |
| **SMTP** | Email notifications | Django email backend |

## 🏛️ Architectural Patterns

### 1. Model-View-Controller (MVC)

```
Models (Django ORM)
    ↓
Views (Django Views/ViewSets)
    ↓
Templates/API Responses
```

### 2. Repository Pattern

```python
class CompoundRepository:
    def get_by_chembl_id(self, chembl_id: str) -> Compound:
        pass
    
    def search_by_name(self, name: str) -> QuerySet[Compound]:
        pass
    
    def get_interactions(self, compound: Compound) -> QuerySet[Interaction]:
        pass
```

### 3. Service Layer Pattern

```python
class CompoundService:
    def __init__(self, repository: CompoundRepository):
        self.repository = repository
    
    def import_from_chembl(self, chembl_id: str) -> Compound:
        # Business logic for ChEMBL import
        pass
    
    def calculate_interactions(self, compound: Compound) -> List[Interaction]:
        # Business logic for interaction calculation
        pass
```

### 4. Command Pattern (Management Commands)

```python
class Command(BaseCommand):
    def add_arguments(self, parser):
        # Define command arguments
        pass
    
    def handle(self, *args, **options):
        # Execute command logic
        pass
```

## 📊 Data Flow Architecture

### 1. API Request Flow

```
Client Request
    ↓
Django URL Router
    ↓
Middleware (Auth, CORS, etc.)
    ↓
View/ViewSet
    ↓
Serializer (Validation)
    ↓
Service Layer
    ↓
Repository Layer
    ↓
Django ORM
    ↓
Database
```

### 2. ChEMBL Import Flow

```
Management Command
    ↓
ChEMBL Importer Service
    ↓
External ChEMBL API
    ↓
Data Processing
    ↓
Database Storage
    ↓
Interaction Calculation
    ↓
Cache Update
```

### 3. User Interaction Flow

```
Frontend (React)
    ↓ HTTP/HTTPS
Django REST API
    ↓ JWT Token
Authentication Middleware
    ↓ Validated Request
Business Logic (Services)
    ↓ Data Access
Database (PostgreSQL)
    ↓ Response
JSON API Response
    ↓ State Update
Frontend UI Update
```

## 🗃️ Database Architecture

### Entity Relationship Overview

```
Users ──┐
        │
        ├── Profiles
        ├── IntakeLogs
        ├── ResearchSnippets
        └── ChangeRequests
              │
Compounds ────┼── CompoundTargetInteractions ── Targets
        │     │
        ├─────┼── CompoundToCompoundInteractions
        │     │
        └─────┴── Reviews
```

### Key Relationships

| Relationship | Type | Description |
|--------------|------|-------------|
| User → Profile | One-to-One | User profile information |
| User → IntakeLog | One-to-Many | User's compound intake records |
| Compound → Target | Many-to-Many | Compound-target interactions |
| Compound → Compound | Many-to-Many | Compound-compound interactions |
| ResearchSnippet → User | Many-to-One | Research authored by users |

### Database Optimization

#### Indexing Strategy
```sql
-- Compound lookups
CREATE INDEX idx_compound_chembl_id ON compounds_compound(chembl_id);
CREATE INDEX idx_compound_name ON compounds_compound(name);

-- Interaction queries
CREATE INDEX idx_interaction_compound ON compounds_compoundtargetinteraction(compound_id);
CREATE INDEX idx_interaction_target ON compounds_compoundtargetinteraction(target_id);

-- User activity
CREATE INDEX idx_intake_user_date ON logs_intakelog(user_id, date_time);
```

#### Query Optimization
- Use `select_related()` for foreign key relationships
- Use `prefetch_related()` for many-to-many relationships
- Implement database-level constraints
- Use database views for complex queries

## 🔒 Security Architecture

### Authentication & Authorization

```
Request → JWT Token Validation → Permission Check → View Access
```

#### Security Layers

1. **Network Security**
   - HTTPS enforcement
   - CORS configuration
   - Rate limiting

2. **Application Security**
   - JWT token authentication
   - Permission-based access control
   - Input validation and sanitization

3. **Data Security**
   - Database encryption at rest
   - Sensitive data hashing
   - SQL injection prevention

### Security Middleware Stack

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'rest_framework.middleware.RateLimitMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
```

## 📈 Performance Architecture

### Caching Strategy

#### Multi-Layer Caching
```
Browser Cache (HTTP Headers)
    ↓
CDN Cache (Static Files)
    ↓
Redis Cache (API Responses)
    ↓
Database Query Cache
    ↓
Database
```

#### Cache Implementation
```python
from django.core.cache import cache

class CompoundService:
    def get_compound_data(self, chembl_id: str):
        cache_key = f"compound:{chembl_id}"
        data = cache.get(cache_key)
        
        if data is None:
            data = self.fetch_from_database(chembl_id)
            cache.set(cache_key, data, timeout=3600)
        
        return data
```

### Database Performance

#### Connection Pooling
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'OPTIONS': {
            'MAX_CONNS': 20,
            'CONN_MAX_AGE': 60,
        }
    }
}
```

#### Query Optimization
- Database query analysis
- Slow query logging
- Index optimization
- Query result caching

## 🔄 Scalability Architecture

### Horizontal Scaling

#### Load Balancer Configuration
```nginx
upstream neurobin_app {
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
}

server {
    listen 80;
    location / {
        proxy_pass http://neurobin_app;
    }
}
```

#### Database Scaling
- Read replicas for query distribution
- Database sharding by data type
- Connection pooling

### Vertical Scaling

#### Resource Optimization
- Memory usage optimization
- CPU utilization monitoring
- I/O performance tuning

## 🧪 Testing Architecture

### Testing Strategy

#### Test Pyramid
```
End-to-End Tests (Frontend + Backend)
    ↓
Integration Tests (API Tests)
    ↓
Unit Tests (Model, Service, View Tests)
```

#### Test Organization
```
tests/
├── unit/
│   ├── test_models.py
│   ├── test_services.py
│   └── test_utils.py
├── integration/
│   ├── test_api.py
│   └── test_imports.py
└── e2e/
    ├── test_user_flows.py
    └── test_admin_workflows.py
```

## 🚀 Deployment Architecture

### Development Environment
```
Developer Machine
    ↓ git push
GitHub Repository
    ↓ webhook
CI/CD Pipeline
    ↓ deploy
Staging Environment
```

### Production Environment
```
Load Balancer (Nginx)
    ↓
Application Servers (Gunicorn)
    ↓
Database (PostgreSQL)
    ↓
Cache (Redis)
    ↓
File Storage (Static/Media)
```

### CI/CD Pipeline
```yaml
# .github/workflows/deploy.yml
on: [push]
jobs:
  test:
    - Run tests
    - Code quality checks
  deploy:
    - Build application
    - Deploy to staging
    - Run integration tests
    - Deploy to production
```

## 🔧 Configuration Management

### Environment-Based Configuration

#### Development
```python
DEBUG = True
ALLOWED_HOSTS = ['localhost', '127.0.0.1']
DATABASE_URL = 'sqlite:///db.sqlite3'
```

#### Staging
```python
DEBUG = True
ALLOWED_HOSTS = ['staging.neurob.in']
DATABASE_URL = 'postgresql://user:pass@staging-db:5432/neurobin'
```

#### Production
```python
DEBUG = False
ALLOWED_HOSTS = ['neurob.in', 'www.neurob.in']
DATABASE_URL = 'postgresql://user:pass@prod-db:5432/neurobin'
```

## 📊 Monitoring & Observability

### Application Monitoring
- Error tracking (Sentry)
- Performance monitoring (APM)
- User analytics
- API usage metrics

### Infrastructure Monitoring
- Server resource usage
- Database performance
- Cache hit rates
- Network latency

### Logging Strategy
```python
LOGGING = {
    'version': 1,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': 'django.log',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'INFO',
        },
    },
}
```

## 🔮 Future Architecture Considerations

### Microservices Migration
- Service decomposition strategy
- API gateway implementation
- Service discovery
- Distributed tracing

### Event-Driven Architecture
- Message queues (RabbitMQ/Apache Kafka)
- Event sourcing
- CQRS pattern implementation

### Cloud-Native Architecture
- Containerization (Docker)
- Orchestration (Kubernetes)
- Cloud services integration
- Serverless functions

---
*This architecture documentation is a living document that evolves with the platform.*
