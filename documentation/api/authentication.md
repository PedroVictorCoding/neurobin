# API Authentication Guide

Complete guide to authenticating with the Neurobin REST API.

## 🔐 Authentication Overview

The Neurobin API uses **JWT (JSON Web Token)** authentication for secure access to protected endpoints. This guide covers all authentication methods and best practices.

## 🚀 Quick Start

### 1. Obtain Access Token

```http
POST /api/token/
Content-Type: application/json

{
    "username": "your_username",
    "password": "your_password"
}
```

**Response:**
```json
{
    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

### 2. Use Access Token

```http
GET /api/compounds/
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

### 3. Refresh Token When Expired

```http
POST /api/token/refresh/
Content-Type: application/json

{
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

## 🛠️ Implementation Examples

### JavaScript/Fetch API

```javascript
class NeurobinAPI {
    constructor(baseURL = 'http://localhost:9000/api') {
        this.baseURL = baseURL;
        this.accessToken = localStorage.getItem('access_token');
        this.refreshToken = localStorage.getItem('refresh_token');
    }

    async login(username, password) {
        const response = await fetch(`${this.baseURL}/token/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, password }),
        });

        if (response.ok) {
            const data = await response.json();
            this.accessToken = data.access;
            this.refreshToken = data.refresh;
            
            localStorage.setItem('access_token', this.accessToken);
            localStorage.setItem('refresh_token', this.refreshToken);
            
            return data;
        } else {
            throw new Error('Authentication failed');
        }
    }

    async refreshAccessToken() {
        const response = await fetch(`${this.baseURL}/token/refresh/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ refresh: this.refreshToken }),
        });

        if (response.ok) {
            const data = await response.json();
            this.accessToken = data.access;
            localStorage.setItem('access_token', this.accessToken);
            return data;
        } else {
            // Refresh token expired, need to login again
            this.logout();
            throw new Error('Session expired');
        }
    }

    async apiCall(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };

        if (this.accessToken) {
            headers.Authorization = `Bearer ${this.accessToken}`;
        }

        let response = await fetch(url, {
            ...options,
            headers,
        });

        // Handle token expiration
        if (response.status === 401 && this.refreshToken) {
            try {
                await this.refreshAccessToken();
                headers.Authorization = `Bearer ${this.accessToken}`;
                response = await fetch(url, {
                    ...options,
                    headers,
                });
            } catch (error) {
                throw new Error('Authentication required');
            }
        }

        return response;
    }

    logout() {
        this.accessToken = null;
        this.refreshToken = null;
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    }
}

// Usage example
const api = new NeurobinAPI();

// Login
await api.login('username', 'password');

// Make authenticated requests
const response = await api.apiCall('/compounds/');
const compounds = await response.json();
```

### Python/Requests

```python
import requests
import json
from datetime import datetime, timedelta

class NeurobinAPI:
    def __init__(self, base_url='http://localhost:9000/api'):
        self.base_url = base_url
        self.access_token = None
        self.refresh_token = None
        self.session = requests.Session()

    def login(self, username, password):
        """Authenticate and obtain tokens."""
        response = self.session.post(
            f'{self.base_url}/token/',
            json={'username': username, 'password': password}
        )
        
        if response.status_code == 200:
            data = response.json()
            self.access_token = data['access']
            self.refresh_token = data['refresh']
            self.session.headers.update({
                'Authorization': f'Bearer {self.access_token}'
            })
            return data
        else:
            raise Exception('Authentication failed')

    def refresh_access_token(self):
        """Refresh the access token using refresh token."""
        response = self.session.post(
            f'{self.base_url}/token/refresh/',
            json={'refresh': self.refresh_token}
        )
        
        if response.status_code == 200:
            data = response.json()
            self.access_token = data['access']
            self.session.headers.update({
                'Authorization': f'Bearer {self.access_token}'
            })
            return data
        else:
            raise Exception('Token refresh failed')

    def api_request(self, method, endpoint, **kwargs):
        """Make authenticated API request with automatic token refresh."""
        url = f'{self.base_url}{endpoint}'
        
        response = self.session.request(method, url, **kwargs)
        
        # Handle token expiration
        if response.status_code == 401 and self.refresh_token:
            try:
                self.refresh_access_token()
                response = self.session.request(method, url, **kwargs)
            except Exception:
                raise Exception('Authentication required')
        
        return response

    def get_compounds(self, **params):
        """Get compounds with optional filtering."""
        response = self.api_request('GET', '/compounds/', params=params)
        return response.json()

    def create_compound(self, compound_data):
        """Create a new compound."""
        response = self.api_request('POST', '/compounds/', json=compound_data)
        return response.json()

# Usage example
api = NeurobinAPI()

# Login
api.login('username', 'password')

# Get compounds
compounds = api.get_compounds(search='caffeine')

# Create compound
new_compound = api.create_compound({
    'name': 'Test Compound',
    'smiles': 'CCO',
    'description': 'Test compound for API'
})
```

### cURL Examples

```bash
# 1. Login and get tokens
curl -X POST http://localhost:9000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}' \
  | jq '.'

# Response:
# {
#   "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
#   "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
# }

# 2. Use access token for authenticated requests
export ACCESS_TOKEN="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."

curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  http://localhost:9000/api/compounds/ | jq '.'

# 3. Refresh token when expired
export REFRESH_TOKEN="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."

curl -X POST http://localhost:9000/api/token/refresh/ \
  -H "Content-Type: application/json" \
  -d "{\"refresh\": \"$REFRESH_TOKEN\"}" \
  | jq '.'

# 4. Create a new compound
curl -X POST http://localhost:9000/api/compounds/ \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Compound",
    "smiles": "CCO",
    "description": "Test compound created via API"
  }' | jq '.'
```

## 🔑 Token Management

### Token Lifecycle

| Token Type | Purpose | Lifetime | Renewal |
|------------|---------|----------|---------|
| **Access Token** | API authentication | 1 hour | Use refresh token |
| **Refresh Token** | Token renewal | 24 hours | Re-authenticate |

### Best Practices

#### 1. Secure Token Storage
```javascript
// ✅ Good: Use secure storage
const tokenStorage = {
    set: (key, value) => {
        // Use secure storage like encrypted localStorage
        localStorage.setItem(key, btoa(value)); // Basic encoding
    },
    get: (key) => {
        const value = localStorage.getItem(key);
        return value ? atob(value) : null;
    },
    remove: (key) => {
        localStorage.removeItem(key);
    }
};

// ❌ Bad: Plain text storage
localStorage.setItem('token', accessToken);
```

#### 2. Automatic Token Refresh
```javascript
class TokenManager {
    constructor() {
        this.setupAutoRefresh();
    }

    setupAutoRefresh() {
        // Refresh token 5 minutes before expiration
        const refreshInterval = 55 * 60 * 1000; // 55 minutes
        
        setInterval(async () => {
            if (this.isTokenNearExpiry()) {
                await this.refreshToken();
            }
        }, refreshInterval);
    }

    isTokenNearExpiry() {
        if (!this.accessToken) return false;
        
        const payload = JSON.parse(atob(this.accessToken.split('.')[1]));
        const expiry = payload.exp * 1000;
        const now = Date.now();
        const fiveMinutes = 5 * 60 * 1000;
        
        return expiry - now < fiveMinutes;
    }
}
```

#### 3. Error Handling
```javascript
async function handleAPICall(apiFunction) {
    try {
        return await apiFunction();
    } catch (error) {
        if (error.status === 401) {
            // Token expired
            await refreshToken();
            return await apiFunction();
        } else if (error.status === 403) {
            // Insufficient permissions
            throw new Error('Access denied');
        } else {
            throw error;
        }
    }
}
```

## 🚫 Authentication Errors

### Common Error Responses

#### 401 Unauthorized
```json
{
    "detail": "Given token not valid for any token type",
    "code": "token_not_valid",
    "messages": [
        {
            "token_class": "AccessToken",
            "token_type": "access",
            "message": "Token is invalid or expired"
        }
    ]
}
```

**Solutions:**
- Check token format and validity
- Refresh the access token
- Re-authenticate if refresh token expired

#### 403 Forbidden
```json
{
    "detail": "You do not have permission to perform this action."
}
```

**Solutions:**
- Check user permissions
- Ensure user has required role
- Contact administrator for access

#### 400 Bad Request (Login)
```json
{
    "detail": "No active account found with the given credentials"
}
```

**Solutions:**
- Verify username and password
- Check if account is active
- Reset password if necessary

## 🔒 Security Considerations

### 1. HTTPS Requirements
```javascript
// Always use HTTPS in production
const apiURL = process.env.NODE_ENV === 'production' 
    ? 'https://api.neurob.in' 
    : 'http://localhost:9000/api';
```

### 2. Token Validation
```python
import jwt
from django.conf import settings

def validate_token(token):
    try:
        payload = jwt.decode(
            token, 
            settings.SECRET_KEY, 
            algorithms=['HS256']
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise Exception('Token expired')
    except jwt.InvalidTokenError:
        raise Exception('Invalid token')
```

### 3. Rate Limiting
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

## 📱 Client Integration Examples

### React Hook
```javascript
import { useState, useEffect, useContext, createContext } from 'react';

const AuthContext = createContext();

export const useAuth = () => {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider');
    }
    return context;
};

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const token = localStorage.getItem('access_token');
        if (token) {
            validateAndSetUser(token);
        } else {
            setLoading(false);
        }
    }, []);

    const login = async (username, password) => {
        const api = new NeurobinAPI();
        const data = await api.login(username, password);
        setUser({ username, token: data.access });
        return data;
    };

    const logout = () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        setUser(null);
    };

    const value = {
        user,
        login,
        logout,
        loading
    };

    return (
        <AuthContext.Provider value={value}>
            {children}
        </AuthContext.Provider>
    );
};
```

### Vue.js Composable
```javascript
import { ref, computed } from 'vue';

const accessToken = ref(localStorage.getItem('access_token'));
const refreshToken = ref(localStorage.getItem('refresh_token'));

export function useAuth() {
    const isAuthenticated = computed(() => !!accessToken.value);

    const login = async (username, password) => {
        const response = await fetch('/api/token/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        if (response.ok) {
            const data = await response.json();
            accessToken.value = data.access;
            refreshToken.value = data.refresh;
            
            localStorage.setItem('access_token', data.access);
            localStorage.setItem('refresh_token', data.refresh);
            
            return data;
        } else {
            throw new Error('Login failed');
        }
    };

    const logout = () => {
        accessToken.value = null;
        refreshToken.value = null;
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
    };

    return {
        accessToken: readonly(accessToken),
        isAuthenticated,
        login,
        logout
    };
}
```

## 🧪 Testing Authentication

### Unit Tests
```python
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

class AuthenticationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )

    def test_login_success(self):
        response = self.client.post('/api/token/', {
            'username': 'testuser',
            'password': 'testpass123'
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_invalid_credentials(self):
        response = self.client.post('/api/token/', {
            'username': 'testuser',
            'password': 'wrongpassword'
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_request(self):
        # Get token
        response = self.client.post('/api/token/', {
            'username': 'testuser',
            'password': 'testpass123'
        })
        token = response.data['access']

        # Use token for authenticated request
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        response = self.client.get('/api/compounds/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
```

---

## 📚 Related Documentation

- [API Endpoints Reference](./endpoints.md)
- [Complete API Documentation](./API_DOCUMENTATION.md)
- [Security Guide](../technical/SECURITY.md)

---
*For production deployment, ensure all authentication traffic uses HTTPS*
