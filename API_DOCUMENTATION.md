# Django REST Framework API Documentation

This document provides a comprehensive overview of the RESTful API created for the Django project. The API supports full CRUD operations for all models across all apps.

## Base URL
```
http://0.0.0.0:9000/api/
```

## Authentication
The API uses JWT (JSON Web Token) authentication.

### Obtain Token
```
POST /api/token/
Content-Type: application/json

{
    "username": "your_username",
    "password": "your_password"
}
```

### Refresh Token
```
POST /api/token/refresh/
Content-Type: application/json

{
    "refresh": "your_refresh_token"
}
```

### Using Token
Include in Authorization header:
```
Authorization: Bearer <your_access_token>
```

## API Endpoints

### Compounds App

#### CompoundCategories
- **List/Create**: `GET/POST /api/compounds/compoundcategories/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/compounds/compoundcategories/{id}/`

Example:
```json
{
    "id": 1,
    "name": "Nootropics",
    "description": "Cognitive enhancing compounds"
}
```

#### Target
- **List/Create**: `GET/POST /api/compounds/target/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/compounds/target/{id}/`

Example:
```json
{
    "id": 1,
    "name": "GABA-A receptor"
}
```

#### CompoundMechanismOfAction
- **List/Create**: `GET/POST /api/compounds/compoundmechanismofaction/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/compounds/compoundmechanismofaction/{id}/`

Example:
```json
{
    "id": 1,
    "target_name": {"id": 1, "name": "GABA-A receptor"},
    "target_name_id": 1,
    "target_type": "receptor",
    "target_interaction": "agonist",
    "description": "Binds to GABA-A receptor as an agonist"
}
```

#### Compound
- **List/Create**: `GET/POST /api/compounds/compound/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/compounds/compound/{slug}/`
- **Get Ratings**: `GET /api/compounds/compound/{slug}/ratings/`
- **Get Safety Screening**: `GET /api/compounds/compound/{slug}/safety_screening/`

Example:
```json
{
    "id": 1,
    "name": "Phenibut",
    "description": "GABA-B receptor agonist",
    "slug": "phenibut",
    "aliases": "β-phenyl-GABA",
    "smiles": "NCC(CCc1ccccc1)C(O)=O",
    "categories": [{"id": 1, "name": "Nootropics"}],
    "mechanism_of_action": [{"id": 1, "target_name": {"name": "GABA-B receptor"}}],
    "categories_ids": [1],
    "mechanism_of_action_ids": [1]
}
```

#### CompoundRating
- **List/Create**: `GET/POST /api/compounds/compoundrating/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/compounds/compoundrating/{id}/`
- **Filter by compound**: `GET /api/compounds/compoundrating/?compound={compound_id}`

Example:
```json
{
    "id": 1,
    "compound": {"id": 1, "name": "Phenibut"},
    "compound_id": 1,
    "user": "username",
    "score": 4,
    "comment": "Effective for anxiety",
    "created_at": "2025-01-01T12:00:00Z"
}
```

#### CompoundSafetyScreening
- **List/Create**: `GET/POST /api/compounds/compoundsafetyscreening/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/compounds/compoundsafetyscreening/{id}/`
- **Filter by compound**: `GET /api/compounds/compoundsafetyscreening/?compound={compound_id}`

Example:
```json
{
    "id": 1,
    "compound": {"id": 1, "name": "Phenibut"},
    "compound_id": 1,
    "liver_toxicity": 2,
    "kidney_toxicity": 1,
    "cardiovascular_risk": 2,
    "hpta_suppression": 1,
    "neurotoxicity": 2,
    "lung_toxicity": 1,
    "pancreas_toxicity": 1,
    "bladder_toxicity": 1,
    "confidence_score": 4,
    "reference_link": "https://pubmed.ncbi.nlm.nih.gov/example",
    "created_by": "researcher_username",
    "created_at": "2025-01-01T12:00:00Z"
}
```

#### EffectWindow
- **List/Create**: `GET/POST /api/compounds/effectwindow/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/compounds/effectwindow/{id}/`
- **Filter by compound**: `GET /api/compounds/effectwindow/?compound={compound_id}`
- **Get Curve Data**: `GET /api/compounds/effectwindow/{id}/curve_data/?resolution={minutes}`

Example:
```json
{
    "id": 1,
    "compound": {"id": 1, "name": "Phenibut"},
    "compound_id": 1,
    "onset_minutes": 30,
    "peak_min_minutes": 120,
    "peak_max_minutes": 180,
    "duration_minutes": 480,
    "half_life_minutes": 240,
    "effect_shape": "bell",
    "notes": "Typical dosage effect profile",
    "created_by": "researcher_username",
    "created_at": "2025-01-01T12:00:00Z",
    "peak_duration_minutes": 60,
    "comedown_minutes": 300,
    "effect_curve_data": [
        [0, 0],
        [30, 0],
        [60, 25],
        [120, 100],
        [180, 100],
        [240, 50],
        [360, 25],
        [480, 0]
    ]
}
```

Curve Data Response (with custom resolution):
```json
{
    "compound": "Phenibut",
    "effect_shape": "bell",
    "curve_data": [
        [0, 0],
        [30, 0],
        [60, 25],
        [120, 100],
        [180, 100],
        [240, 50],
        [360, 25],
        [480, 0]
    ],
    "metadata": {
        "onset_minutes": 30,
        "peak_min_minutes": 120,
        "peak_max_minutes": 180,
        "duration_minutes": 480,
        "half_life_minutes": 240
    }
}
```

### Accounts App

#### User
- **List**: `GET /api/accounts/user/`
- **Retrieve**: `GET /api/accounts/user/{username}/`
- **Current User**: `GET /api/accounts/user/me/`

Example:
```json
{
    "id": 1,
    "username": "john_doe",
    "email": "john@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "date_joined": "2025-01-01T12:00:00Z",
    "is_active": true
}
```

#### UserProfile
- **List/Create**: `GET/POST /api/accounts/userprofile/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/accounts/userprofile/{id}/`
- **Current User Profile**: `GET /api/accounts/userprofile/me/`

Example:
```json
{
    "id": 1,
    "user": {"id": 1, "username": "john_doe"},
    "user_id": 1,
    "profile_image": "/media/profile_images/profile_1.jpg",
    "profile_image_url": "/media/profile_images/profile_1.jpg",
    "bio": "Researcher interested in nootropics",
    "location": "San Francisco, CA",
    "website": "https://johndoe.com",
    "created_at": "2025-01-01T12:00:00Z",
    "updated_at": "2025-01-01T12:00:00Z"
}
```

### Logs App

#### IntakeLog
- **List/Create**: `GET/POST /api/logs/intakelog/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/logs/intakelog/{id}/`
- **Analytics**: `GET /api/logs/intakelog/analytics/`

Example:
```json
{
    "id": 1,
    "user": "john_doe",
    "compound": {"id": 1, "name": "Phenibut"},
    "compound_id": 1,
    "amount": "500",
    "unit": "mg",
    "taken_at": "2025-01-01T08:00:00Z",
    "notes": "Taken with breakfast for anxiety management"
}
```

Analytics response:
```json
{
    "total_logs": 45,
    "compounds_used": 12,
    "most_used_compound": {
        "compound__name": "Phenibut",
        "count": 15
    }
}
```

### Research App

#### ResearchSnippet
- **List/Create**: `GET/POST /api/research/researchsnippet/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/research/researchsnippet/{id}/`
- **Filter by compound**: `GET /api/research/researchsnippet/?compound={compound_id}`
- **Filter by status**: `GET /api/research/researchsnippet/?status={status}`
- **Increment View**: `POST /api/research/researchsnippet/{id}/increment_view/`
- **Analytics**: `GET /api/research/researchsnippet/{id}/analytics/`

Example:
```json
{
    "id": 1,
    "title": "Phenibut Pharmacokinetics Study",
    "content": "This study examined the absorption and metabolism of phenibut...",
    "compound": {"id": 1, "name": "Phenibut"},
    "compound_id": 1,
    "snippet_type": "pharmacology",
    "visibility": "public",
    "status": "verified",
    "source_title": "Journal of Pharmacology Study",
    "source_url": "https://pubmed.example.com",
    "doi": "10.1234/example",
    "created_by": "researcher",
    "ai_summary": "AI-generated summary...",
    "ai_generated": false,
    "view_count": 150,
    "tags": [{"id": 1, "name": "pharmacokinetics"}],
    "reviews": [{"id": 1, "vote_type": "validate"}],
    "comments": [{"id": 1, "content": "Great research!"}],
    "net_score": {"positive": 5, "negative": 1},
    "confidence_level": "High",
    "confidence_color": "success",
    "created_at": "2025-01-01T12:00:00Z",
    "updated_at": "2025-01-01T12:00:00Z"
}
```

#### SnippetReview
- **List/Create**: `GET/POST /api/research/snippetreview/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/research/snippetreview/{id}/`
- **Filter by snippet**: `GET /api/research/snippetreview/?snippet={snippet_id}`

Example:
```json
{
    "id": 1,
    "snippet_id": 1,
    "reviewer": "expert_user",
    "vote_type": "validate",
    "comment": "Well-researched and accurate information",
    "created_at": "2025-01-01T12:00:00Z"
}
```

#### SnippetTag
- **List/Create**: `GET/POST /api/research/snippettag/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/research/snippettag/{id}/`

Example:
```json
{
    "id": 1,
    "name": "pharmacokinetics",
    "description": "Studies related to drug absorption and metabolism",
    "color": "#007bff",
    "created_at": "2025-01-01T12:00:00Z"
}
```

#### SnippetTagging
- **List/Create**: `GET/POST /api/research/snippettagging/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/research/snippettagging/{id}/`
- **Filter by snippet**: `GET /api/research/snippettagging/?snippet={snippet_id}`

#### UserRole
- **List/Create**: `GET/POST /api/research/userrole/` (Admin only)
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/research/userrole/{id}/` (Admin only)

#### ResearchSettings
- **List/Create**: `GET/POST /api/research/researchsettings/` (Admin only)
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/research/researchsettings/{id}/` (Admin only)

#### SnippetComment
- **List/Create**: `GET/POST /api/research/snippetcomment/`
- **Retrieve/Update/Delete**: `GET/PUT/PATCH/DELETE /api/research/snippetcomment/{id}/`
- **Filter by snippet**: `GET /api/research/snippetcomment/?snippet={snippet_id}`

## HTTP Status Codes

- **200 OK**: Successful GET, PUT, PATCH
- **201 Created**: Successful POST
- **204 No Content**: Successful DELETE
- **400 Bad Request**: Invalid data
- **401 Unauthorized**: Authentication required
- **403 Forbidden**: Permission denied
- **404 Not Found**: Resource not found
- **405 Method Not Allowed**: HTTP method not supported

## Error Response Format

```json
{
    "detail": "Error message here"
}
```

Or for validation errors:
```json
{
    "field_name": ["Error message for this field"],
    "another_field": ["Another error message"]
}
```

## Pagination

List endpoints use pagination with the following response format:
```json
{
    "count": 100,
    "next": "http://localhost:9000/api/endpoint/?page=3",
    "previous": "http://localhost:9000/api/endpoint/?page=1",
    "results": [...]
}
```

Default page size is 20 items. Use `?page=N` to access different pages.

## Permissions

- **IsAuthenticated**: User must be logged in
- **IsAuthenticatedOrReadOnly**: Anonymous users can read, authenticated users can modify
- **IsAdminUser**: Only admin users can access
- **Custom**: Some endpoints have custom permission logic (e.g., users can only see their own data)

## Testing the API

### Using curl:
```bash
# Get token
curl -X POST http://localhost:9000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}'

# Use token to access protected endpoint
curl -H "Authorization: Bearer <your_token>" \
  http://localhost:9000/api/compounds/compound/

# Create a new compound
curl -X POST http://localhost:9000/api/compounds/compound/ \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Compound", "description": "A test compound"}'
```

### Using the Django REST Framework Browsable API:
Visit `http://localhost:9000/api/` in your browser to access the interactive API browser.

## Summary

This API provides complete CRUD functionality for:
- **Compounds App**: 6 models (CompoundCategories, Target, CompoundMechanismOfAction, Compound, CompoundRating, CompoundSafetyScreening)
- **Accounts App**: 2 models (User, UserProfile)
- **Logs App**: 1 model (IntakeLog)
- **Research App**: 7 models (ResearchSnippet, SnippetReview, SnippetTag, SnippetTagging, UserRole, ResearchSettings, SnippetComment)

All endpoints follow RESTful conventions with proper HTTP methods, status codes, and JSON responses. The API includes authentication, permissions, filtering, and pagination as requested.
