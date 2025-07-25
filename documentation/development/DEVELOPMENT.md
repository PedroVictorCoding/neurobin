# Neurobin Development Guide

## Overview

This guide covers development workflow, coding standards, testing procedures, and contribution guidelines for the Neurobin platform.

## Development Environment Setup

### Prerequisites
- **Python:** 3.11+
- **Node.js:** 18+
- **Git:** Latest version
- **IDE:** VS Code / PyCharm (recommended)
- **Database:** SQLite (development) / PostgreSQL (production)

### Initial Setup

```bash
# Clone repository
git clone https://github.com/your-org/neurobin.git
cd neurobin

# Backend setup
cd core/
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

pip install -r requirements.txt
pip install -r requirements-dev.txt  # Development dependencies

# Database setup
python manage.py migrate
python manage.py createsuperuser
python manage.py loaddata fixtures/sample_data.json  # Optional test data

# Frontend setup
cd ../frontend/
npm install
```

### Development Dependencies

#### Backend (requirements-dev.txt)
```
# Testing
pytest==7.4.0
pytest-django==4.5.2
pytest-cov==4.1.0
factory-boy==3.3.0

# Code Quality
black==23.7.0
flake8==6.0.0
isort==5.12.0
mypy==1.5.1

# Development Tools
django-debug-toolbar==4.1.0
django-extensions==3.2.3
ipython==8.14.0

# Documentation
sphinx==7.1.2
sphinx-rtd-theme==1.3.0
```

#### Frontend (package.json - devDependencies)
```json
{
  "devDependencies": {
    "@types/react": "^18.2.15",
    "@types/react-dom": "^18.2.7",
    "@vitejs/plugin-react": "^4.0.3",
    "eslint": "^8.45.0",
    "eslint-plugin-react": "^7.32.2",
    "eslint-plugin-react-hooks": "^4.6.0",
    "eslint-plugin-react-refresh": "^0.4.3",
    "prettier": "^3.0.0",
    "vite": "^4.4.5"
  }
}
```

## Project Structure

### Backend Structure
```
core/
├── manage.py                   # Django management
├── core/                       # Main project settings
│   ├── settings.py            # Django configuration
│   ├── urls.py                # URL routing
│   ├── wsgi.py                # WSGI application
│   └── asgi.py                # ASGI application
├── compounds/                  # Compound management app
│   ├── models.py              # Database models
│   ├── views.py               # Django views
│   ├── api_views.py           # REST API views
│   ├── serializers.py         # API serializers
│   ├── admin.py               # Admin interface
│   ├── urls.py                # URL patterns
│   ├── forms.py               # Django forms
│   ├── tests.py               # Unit tests
│   └── migrations/            # Database migrations
├── research/                   # Research snippets app
├── logs/                       # User logging app
├── accounts/                   # User management app
├── change_requests/            # Change management app
├── templates/                  # HTML templates
│   ├── base.html              # Base template
│   ├── compounds/             # Compound templates
│   ├── research/              # Research templates
│   └── accounts/              # Account templates
├── static/                     # Static assets
│   ├── css/                   # Stylesheets
│   ├── js/                    # JavaScript files
│   └── images/                # Images
├── media/                      # User uploads
└── fixtures/                   # Test data
```

### Frontend Structure
```
frontend/
├── src/
│   ├── components/            # Reusable components
│   │   ├── Layout.jsx         # Main layout
│   │   ├── Navbar.jsx         # Navigation
│   │   └── common/            # Common components
│   ├── pages/                 # Page components
│   │   ├── Home.jsx           # Homepage
│   │   ├── compounds/         # Compound pages
│   │   ├── research/          # Research pages
│   │   └── accounts/          # Account pages
│   ├── contexts/              # React contexts
│   │   └── AuthContext.jsx    # Authentication
│   ├── services/              # API services
│   │   └── apiService.js      # HTTP client
│   ├── utils/                 # Utility functions
│   │   └── helpers.js         # Helper functions
│   ├── assets/                # Static assets
│   ├── App.jsx                # Main app component
│   ├── App.css                # Global styles
│   └── main.jsx               # Entry point
├── public/                    # Public assets
├── package.json               # Dependencies
├── vite.config.js             # Vite configuration
└── eslint.config.js           # ESLint configuration
```

## Coding Standards

### Python/Django Standards

#### Code Formatting
```bash
# Format code with Black
black core/

# Sort imports with isort
isort core/

# Lint with flake8
flake8 core/
```

#### Style Guidelines
```python
# Model example - compounds/models.py
class Compound(models.Model):
    """
    Core compound model representing neurochemical substances.
    
    Attributes:
        name: Unique compound name
        slug: URL-friendly identifier
        description: Detailed compound information
        smiles: SMILES notation for molecular structure
    """
    name = models.CharField(max_length=500, unique=True)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)
    smiles = models.CharField(
        max_length=1000,
        blank=True,
        help_text="SMILES notation for molecular structure"
    )
    
    class Meta:
        ordering = ['name']
        verbose_name = "Compound"
        verbose_name_plural = "Compounds"
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
```

#### API View Standards
```python
# API view example - compounds/api_views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

class CompoundViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing compounds via REST API.
    
    Provides CRUD operations plus custom actions for
    compound interactions and ratings.
    """
    queryset = Compound.objects.all()
    serializer_class = CompoundSerializer
    lookup_field = 'slug'
    
    @action(detail=True, methods=['get'])
    def interactions(self, request, slug=None):
        """Get compound interactions via shared targets."""
        compound = self.get_object()
        interactions = compound.get_interactions()
        
        interaction_data = []
        for interaction in interactions:
            # Process interaction data
            pass
            
        return Response({
            'compound_id': compound.id,
            'compound_name': compound.name,
            'interactions': interaction_data
        })
```

### JavaScript/React Standards

#### Code Formatting
```bash
# Format with Prettier
npx prettier --write src/

# Lint with ESLint
npx eslint src/
```

#### Component Standards
```jsx
// Component example - components/CompoundCard.jsx
import React from 'react';
import { Link } from 'react-router-dom';
import PropTypes from 'prop-types';

/**
 * CompoundCard component for displaying compound summary information.
 * 
 * @param {Object} compound - Compound data object
 * @param {Function} onRating - Callback for rating changes
 */
const CompoundCard = ({ compound, onRating }) => {
  const handleRatingClick = (rating) => {
    if (onRating) {
      onRating(compound.id, rating);
    }
  };

  return (
    <div className="card bg-neurobin-card">
      <div className="card-body">
        <h5 className="card-title">
          <Link to={`/compounds/${compound.slug}`}>
            {compound.name}
          </Link>
        </h5>
        
        <p className="card-text">
          {compound.description?.substring(0, 150)}...
        </p>
        
        <div className="rating-container">
          {[1, 2, 3, 4, 5].map(star => (
            <button
              key={star}
              className={`star ${star <= compound.rating ? 'filled' : ''}`}
              onClick={() => handleRatingClick(star)}
              aria-label={`Rate ${star} stars`}
            >
              ★
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

CompoundCard.propTypes = {
  compound: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string.isRequired,
    slug: PropTypes.string.isRequired,
    description: PropTypes.string,
    rating: PropTypes.number
  }).isRequired,
  onRating: PropTypes.func
};

export default CompoundCard;
```

## Testing

### Backend Testing

#### Unit Tests
```python
# tests/test_models.py
import pytest
from django.test import TestCase
from compounds.models import Compound, CompoundCategories

class CompoundModelTest(TestCase):
    """Test cases for Compound model."""
    
    def setUp(self):
        self.category = CompoundCategories.objects.create(
            name="Test Category",
            description="Test category description"
        )
        
    def test_compound_creation(self):
        """Test compound can be created successfully."""
        compound = Compound.objects.create(
            name="Test Compound",
            description="Test description",
            smiles="CCO"
        )
        
        self.assertEqual(compound.name, "Test Compound")
        self.assertEqual(compound.slug, "test-compound")
        self.assertTrue(compound.id)
        
    def test_compound_str_representation(self):
        """Test compound string representation."""
        compound = Compound.objects.create(name="Test Compound")
        self.assertEqual(str(compound), "Test Compound")
        
    def test_compound_categories_relationship(self):
        """Test many-to-many relationship with categories."""
        compound = Compound.objects.create(name="Test Compound")
        compound.categories.add(self.category)
        
        self.assertIn(self.category, compound.categories.all())
        self.assertIn(compound, self.category.compounds.all())
```

#### API Tests
```python
# tests/test_api.py
import pytest
from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from compounds.models import Compound

class CompoundAPITest(APITestCase):
    """Test cases for Compound API endpoints."""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.compound = Compound.objects.create(
            name="Test Compound",
            description="Test description"
        )
        
    def test_get_compound_list(self):
        """Test retrieving compound list."""
        url = '/api/compounds/compound/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['name'], "Test Compound")
        
    def test_get_compound_detail(self):
        """Test retrieving compound detail."""
        url = f'/api/compounds/compound/{self.compound.slug}/'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], "Test Compound")
        
    def test_create_compound_requires_authentication(self):
        """Test compound creation requires authentication."""
        url = '/api/compounds/compound/'
        data = {'name': 'New Compound'}
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
```

#### Running Tests
```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test compounds

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test
python manage.py test compounds.tests.test_models.CompoundModelTest.test_compound_creation
```

### Frontend Testing

#### Component Tests
```jsx
// tests/CompoundCard.test.jsx
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import CompoundCard from '../components/CompoundCard';

const mockCompound = {
  id: 1,
  name: "Test Compound",
  slug: "test-compound",
  description: "Test description for compound",
  rating: 3
};

const renderWithRouter = (component) => {
  return render(
    <BrowserRouter>
      {component}
    </BrowserRouter>
  );
};

describe('CompoundCard', () => {
  test('renders compound information correctly', () => {
    renderWithRouter(<CompoundCard compound={mockCompound} />);
    
    expect(screen.getByText('Test Compound')).toBeInTheDocument();
    expect(screen.getByText(/Test description/)).toBeInTheDocument();
  });
  
  test('calls onRating when star is clicked', () => {
    const mockOnRating = jest.fn();
    renderWithRouter(
      <CompoundCard compound={mockCompound} onRating={mockOnRating} />
    );
    
    const fourthStar = screen.getByLabelText('Rate 4 stars');
    fireEvent.click(fourthStar);
    
    expect(mockOnRating).toHaveBeenCalledWith(1, 4);
  });
  
  test('displays correct number of filled stars', () => {
    renderWithRouter(<CompoundCard compound={mockCompound} />);
    
    const filledStars = screen.getAllByText('★').filter(
      star => star.classList.contains('filled')
    );
    expect(filledStars).toHaveLength(3);
  });
});
```

#### Running Frontend Tests
```bash
# Run all tests
npm test

# Run tests with coverage
npm run test:coverage

# Run tests in watch mode
npm run test:watch
```

## Git Workflow

### Branch Strategy
```
main                    # Production-ready code
├── develop            # Integration branch
├── feature/compound-interactions  # Feature branches
├── bugfix/rating-validation      # Bug fix branches
└── hotfix/security-patch         # Hotfix branches
```

### Commit Message Convention
```
type(scope): description

Types:
- feat: New feature
- fix: Bug fix
- docs: Documentation changes
- style: Code formatting
- refactor: Code refactoring
- test: Test additions
- chore: Maintenance tasks

Examples:
feat(compounds): add compound interaction system
fix(research): resolve snippet validation bug
docs(api): update authentication documentation
test(models): add compound model tests
```

### Pull Request Process
1. **Create Feature Branch**
   ```bash
   git checkout -b feature/compound-interactions
   ```

2. **Development & Testing**
   ```bash
   # Make changes, commit regularly
   git add .
   git commit -m "feat(compounds): implement interaction models"
   
   # Run tests before pushing
   python manage.py test
   npm test
   ```

3. **Push and Create PR**
   ```bash
   git push origin feature/compound-interactions
   # Create PR on GitHub/GitLab
   ```

4. **Code Review Checklist**
   - [ ] Code follows style guidelines
   - [ ] Tests pass and cover new code
   - [ ] Documentation updated
   - [ ] No security vulnerabilities
   - [ ] Performance considerations addressed

## Database Management

### Migrations
```bash
# Create migration for model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Show migration status
python manage.py showmigrations

# Rollback migration
python manage.py migrate compounds 0001

# Create empty migration for data migration
python manage.py makemigrations --empty compounds
```

### Data Migrations
```python
# migrations/0002_populate_categories.py
from django.db import migrations

def populate_categories(apps, schema_editor):
    CompoundCategories = apps.get_model('compounds', 'CompoundCategories')
    
    categories = [
        ('Nootropics', 'Cognitive enhancement compounds'),
        ('Psychedelics', 'Psychoactive substances'),
        ('Stimulants', 'Central nervous system stimulants'),
    ]
    
    for name, description in categories:
        CompoundCategories.objects.get_or_create(
            name=name,
            defaults={'description': description}
        )

def reverse_populate_categories(apps, schema_editor):
    CompoundCategories = apps.get_model('compounds', 'CompoundCategories')
    CompoundCategories.objects.all().delete()

class Migration(migrations.Migration):
    dependencies = [
        ('compounds', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            populate_categories,
            reverse_populate_categories
        ),
    ]
```

## Performance Optimization

### Database Optimization
```python
# Use select_related for foreign keys
compounds = Compound.objects.select_related('safety_report').all()

# Use prefetch_related for many-to-many
compounds = Compound.objects.prefetch_related('categories', 'mechanism_of_action').all()

# Add database indexes
class Meta:
    indexes = [
        models.Index(fields=['name']),
        models.Index(fields=['created_at']),
        models.Index(fields=['status', 'created_at']),
    ]
```

### Frontend Optimization
```jsx
// Use React.memo for expensive components
const CompoundCard = React.memo(({ compound, onRating }) => {
  // Component implementation
}, (prevProps, nextProps) => {
  return prevProps.compound.id === nextProps.compound.id;
});

// Use useMemo for expensive calculations
const sortedCompounds = useMemo(() => {
  return compounds.sort((a, b) => a.name.localeCompare(b.name));
}, [compounds]);

// Use useCallback for stable function references
const handleRating = useCallback((compoundId, rating) => {
  // Rating logic
}, []);
```

## Debugging

### Backend Debugging
```python
# settings.py - Debug toolbar
if DEBUG:
    INSTALLED_APPS += ['debug_toolbar']
    MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
    INTERNAL_IPS = ['127.0.0.1', '::1']

# Use pdb for debugging
import pdb; pdb.set_trace()

# Use logging
import logging
logger = logging.getLogger(__name__)
logger.debug(f"Processing compound: {compound.name}")
```

### Frontend Debugging
```jsx
// Use React DevTools
// Install: chrome-extension://fmkadmapgofadopljbjfkapdkoienihi

// Console debugging
console.log('Compound data:', compound);
console.table(compounds);

// React Error Boundaries
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.log('Error caught:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return <h1>Something went wrong.</h1>;
    }
    return this.props.children;
  }
}
```

## Contributing Guidelines

### Before Contributing
1. **Read Documentation:** Review project documentation thoroughly
2. **Check Issues:** Look for existing issues or create new ones
3. **Discuss Changes:** Discuss major changes in issues first
4. **Setup Environment:** Follow development setup instructions

### Contribution Process
1. **Fork Repository:** Create personal fork of the project
2. **Create Branch:** Create feature branch from develop
3. **Make Changes:** Implement changes with tests
4. **Test Thoroughly:** Run all tests and manual testing
5. **Document Changes:** Update documentation as needed
6. **Submit PR:** Create pull request with detailed description

### Code Review Guidelines
- **Be Constructive:** Provide helpful, specific feedback
- **Test Changes:** Verify changes work as expected
- **Check Standards:** Ensure code follows project standards
- **Consider Impact:** Think about broader system impact
- **Approve Thoughtfully:** Only approve when confident in changes

---

**Development Guide Version:** 1.0  
**Last Updated:** July 2025  
**Target Audience:** Developers and Contributors
