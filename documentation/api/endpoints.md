# API Endpoints Reference

Quick reference for all available API endpoints in the Neurobin platform.

## 📍 Base URL
```
http://localhost:9000/api/    # Development
https://api.neurob.in/        # Production
```

## 🔐 Authentication
All endpoints marked with 🔒 require JWT authentication. See [Authentication Guide](./authentication.md) for details.

```http
Authorization: Bearer <your_jwt_token>
```

## 📊 API Overview

| Category | Endpoints | Description |
|----------|-----------|-------------|
| **Authentication** | `/token/` | User authentication and token management |
| **Compounds** | `/compounds/` | Compound database operations |
| **Targets** | `/targets/` | Molecular targets management |
| **Interactions** | `/interactions/` | Compound-target interactions |
| **Research** | `/research/` | Research snippets and reviews |
| **Logs** | `/logs/` | User intake logging |
| **Accounts** | `/users/`, `/profiles/` | User management |

## 🔑 Authentication Endpoints

### Obtain Token
```http
POST /api/token/
```
**Request Body:**
```json
{
    "username": "string",
    "password": "string"
}
```
**Response:**
```json
{
    "access": "jwt_access_token",
    "refresh": "jwt_refresh_token"
}
```

### Refresh Token
```http
POST /api/token/refresh/
```
**Request Body:**
```json
{
    "refresh": "jwt_refresh_token"
}
```

### Verify Token
```http
POST /api/token/verify/
```
**Request Body:**
```json
{
    "token": "jwt_token_to_verify"
}
```

## 🧪 Compounds Endpoints

### List Compounds
```http
GET /api/compounds/
```
**Query Parameters:**
- `search` - Search by name or ChEMBL ID
- `category` - Filter by category
- `ordering` - Sort results (`name`, `-created_at`)
- `page` - Page number for pagination
- `page_size` - Results per page (default: 20)

**Example:**
```http
GET /api/compounds/?search=caffeine&ordering=name&page=1
```

**Response:**
```json
{
    "count": 150,
    "next": "http://localhost:9000/api/compounds/?page=2",
    "previous": null,
    "results": [
        {
            "id": 1,
            "name": "Caffeine",
            "chembl_id": "CHEMBL25",
            "smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
            "description": "Central nervous system stimulant",
            "category": ["Stimulant", "Therapeutic"],
            "created_at": "2025-07-20T10:00:00Z",
            "updated_at": "2025-07-20T15:30:00Z"
        }
    ]
}
```

### Compound Autocomplete (Select2 / AJAX)
```http
GET /api/compounds/compound-search/?q={query}&limit=20
```
Returns a compact list used for fast dropdown searching (name + aliases).

### Get Compound Details 🔒
```http
GET /api/compounds/{id}/
```
**Response:**
```json
{
    "id": 1,
    "name": "Caffeine",
    "chembl_id": "CHEMBL25",
    "smiles": "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
    "description": "Central nervous system stimulant",
    "category": ["Stimulant", "Therapeutic"],
    "aliases": ["1,3,7-trimethylxanthine"],
    "molecular_weight": 194.19,
    "interactions": [
        {
            "target": "Adenosine A2a receptor",
            "mechanism": "antagonist",
            "affinity_level": "high"
        }
    ],
    "created_at": "2025-07-20T10:00:00Z",
    "updated_at": "2025-07-20T15:30:00Z"
}
```

### Create Compound 🔒
```http
POST /api/compounds/
```
**Request Body:**
```json
{
    "name": "Test Compound",
    "chembl_id": "CHEMBL123456",
    "smiles": "CCO",
    "description": "Test compound for API",
    "category": ["Experimental"]
}
```

### Update Compound 🔒
```http
PUT /api/compounds/{id}/
PATCH /api/compounds/{id}/
```

### Delete Compound 🔒
```http
DELETE /api/compounds/{id}/
```

### Compound Interactions
```http
GET /api/compounds/{id}/interactions/
```
**Response:**
```json
{
    "results": [
        {
            "target": {
                "id": 15,
                "name": "Adenosine A2a receptor",
                "target_type": "single protein",
                "organism": "Homo sapiens"
            },
            "mechanism": "antagonist",
            "affinity_level": "high",
            "source": "chembl"
        }
    ]
}
```

## 🎯 Targets Endpoints

### List Targets
```http
GET /api/targets/
```
**Query Parameters:**
- `search` - Search by name
- `target_type` - Filter by type
- `organism` - Filter by organism

### Get Target Details
```http
GET /api/targets/{id}/
```

### Target Compounds
```http
GET /api/targets/{id}/compounds/
```

## 🔗 Interactions Endpoints

### List Compound-Target Interactions
```http
GET /api/interactions/
```
**Query Parameters:**
- `compound` - Filter by compound ID
- `target` - Filter by target ID
- `mechanism` - Filter by mechanism type

### Get Interaction Details
```http
GET /api/interactions/{id}/
```

### Compound-to-Compound Interactions
```http
GET /api/compound-interactions/
```

## 📝 Research Endpoints

### List Research Snippets 🔒
```http
GET /api/research/
```
**Query Parameters:**
- `search` - Search by title or content
- `author` - Filter by author
- `compound` - Filter by related compound

### Create Research Snippet 🔒
```http
POST /api/research/
```
**Request Body:**
```json
{
    "title": "Caffeine Metabolism Study",
    "content": "Research findings on caffeine metabolism...",
    "compound": 1,
    "tags": ["metabolism", "pharmacokinetics"]
}
```

### Research Reviews 🔒
```http
GET /api/research/{id}/reviews/
POST /api/research/{id}/reviews/
```

## 📊 Logs Endpoints

### List Intake Logs 🔒
```http
GET /api/logs/
```
**Query Parameters:**
- `date_from` - Filter by start date
- `date_to` - Filter by end date
- `compound` - Filter by compound

### Create Intake Log 🔒
```http
POST /api/logs/
```
**Request Body:**
```json
{
    "compound": 1,
    "amount": 100.0,
    "unit": "mg",
    "date_time": "2025-07-24T10:00:00Z",
    "notes": "Morning dose"
}
```

### Analytics 🔒
```http
GET /api/logs/analytics/
```

## 👤 User Endpoints

### List Users (Admin only) 🔒
```http
GET /api/users/
```

### Get User Profile 🔒
```http
GET /api/users/{id}/
GET /api/users/me/  # Current user
```

### Update Profile 🔒
```http
PATCH /api/users/me/
```

### User Profiles 🔒
```http
GET /api/profiles/
GET /api/profiles/{id}/
```

## 📱 Response Formats

### Success Response
```json
{
    "id": 1,
    "name": "Compound Name",
    "created_at": "2025-07-24T10:00:00Z"
}
```

### Paginated Response
```json
{
    "count": 100,
    "next": "http://localhost:9000/api/compounds/?page=2",
    "previous": null,
    "results": [...]
}
```

### Error Response
```json
{
    "detail": "Error message",
    "code": "error_code",
    "field_errors": {
        "field_name": ["Field-specific error message"]
    }
}
```

## 🔢 HTTP Status Codes

| Code | Meaning | Description |
|------|---------|-------------|
| `200` | OK | Request successful |
| `201` | Created | Resource created successfully |
| `204` | No Content | Resource deleted successfully |
| `400` | Bad Request | Invalid request data |
| `401` | Unauthorized | Authentication required |
| `403` | Forbidden | Permission denied |
| `404` | Not Found | Resource not found |
| `429` | Too Many Requests | Rate limit exceeded |
| `500` | Server Error | Internal server error |

## 🔍 Search and Filtering

### Text Search
```http
GET /api/compounds/?search=caffeine
```

### Multiple Filters
```http
GET /api/compounds/?category=Stimulant&ordering=-created_at
```

### Advanced Filtering
```http
GET /api/interactions/?compound=1&mechanism=antagonist&affinity_level=high
```

## 📄 Pagination

### Request
```http
GET /api/compounds/?page=2&page_size=10
```

### Response Headers
```http
X-Total-Count: 150
X-Page-Count: 15
X-Current-Page: 2
X-Per-Page: 10
```

## 🚀 Rate Limiting

| User Type | Limit | Window |
|-----------|-------|--------|
| **Anonymous** | 100 requests | 1 hour |
| **Authenticated** | 1000 requests | 1 hour |
| **Admin** | 5000 requests | 1 hour |

### Rate Limit Headers
```http
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 999
X-RateLimit-Reset: 1627890000
```

## 💡 Best Practices

### 1. Use Appropriate HTTP Methods
```http
GET    /api/compounds/      # List resources
POST   /api/compounds/      # Create resource
GET    /api/compounds/1/    # Get specific resource
PUT    /api/compounds/1/    # Update entire resource
PATCH  /api/compounds/1/    # Update partial resource
DELETE /api/compounds/1/    # Delete resource
```

### 2. Handle Pagination
```javascript
async function getAllCompounds() {
    let allCompounds = [];
    let nextUrl = '/api/compounds/';
    
    while (nextUrl) {
        const response = await fetch(nextUrl);
        const data = await response.json();
        allCompounds.push(...data.results);
        nextUrl = data.next;
    }
    
    return allCompounds;
}
```

### 3. Error Handling
```javascript
try {
    const response = await fetch('/api/compounds/', {
        method: 'POST',
        headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(compoundData)
    });
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'API request failed');
    }
    
    const data = await response.json();
    return data;
} catch (error) {
    console.error('API Error:', error.message);
    throw error;
}
```

### 4. Use Filters and Search
```javascript
// Good: Use API filtering
const stimulants = await fetch('/api/compounds/?category=Stimulant');

// Bad: Fetch all and filter client-side
const all = await fetch('/api/compounds/');
const stimulants = all.results.filter(c => c.category.includes('Stimulant'));
```

## 🧪 Testing Endpoints

### cURL Examples
```bash
# Login
curl -X POST http://localhost:9000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "testpass"}'

# Get compounds
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:9000/api/compounds/

# Create compound
curl -X POST http://localhost:9000/api/compounds/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Compound", "smiles": "CCO"}'
```

### Postman Collection
A Postman collection is available at `/docs/postman/neurobin-api.json` with pre-configured requests for all endpoints.

## 📚 Related Documentation

- [Authentication Guide](./authentication.md) - Detailed authentication flow
- [Complete API Documentation](./API_DOCUMENTATION.md) - Full API reference
- [Quick Start Guide](../setup/QUICKSTART.md) - Getting started

---
*This endpoint reference is automatically updated with API changes*
