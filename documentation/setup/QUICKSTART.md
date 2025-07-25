# Quick Start Guide

Get up and running with Neurobin in just a few minutes!

## 🚀 Prerequisites

- **Python 3.11+**
- **Git**
- **Virtual Environment** (recommended)

## ⚡ 5-Minute Setup

### 1. Clone the Repository
```bash
git clone https://github.com/PedroVictorCoding/neurobin.git
cd neurobin
```

### 2. Set Up Python Environment
```bash
cd core/
python -m venv venv

# Activate virtual environment
# Linux/Mac:
source venv/bin/activate
# Windows:
venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Initialize Database
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Start the Server
```bash
python manage.py runserver 0.0.0.0:9000
```

### 6. Access the Platform
- **Main Platform**: http://localhost:9000
- **Admin Panel**: http://localhost:9000/admin
- **API**: http://localhost:9000/api

## 🎯 First Steps

### Create Your First Compound
1. Go to http://localhost:9000/admin
2. Log in with your superuser credentials
3. Navigate to "Compounds" → "Add Compound"
4. Fill in basic compound information

### Import ChEMBL Data
```bash
# Import specific compounds
python manage.py import_chembl_interactions --compounds CHEMBL25,CHEMBL154

# Import with phase filtering
python manage.py import_chembl_interactions --compounds CHEMBL25 --phase-filter "4"
```

### Explore the API
```bash
# Get API token
curl -X POST http://localhost:9000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}'

# List compounds
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:9000/api/compounds/
```

## 🔧 Configuration Options

### Environment Variables
Create a `.env` file in the `core/` directory:
```env
DEBUG=True
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///db.sqlite3
ALLOWED_HOSTS=localhost,127.0.0.1
```

### Admin Configuration
- **Superuser**: Create with `python manage.py createsuperuser`
- **User Management**: Available at `/admin/auth/user/`
- **Compound Management**: Available at `/admin/compounds/`

## 🔍 Troubleshooting

### Common Issues

**Issue**: `ModuleNotFoundError: No module named 'django'`
```bash
# Solution: Activate virtual environment
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

**Issue**: Database migrations error
```bash
# Solution: Reset database
rm db.sqlite3
python manage.py migrate
python manage.py createsuperuser
```

**Issue**: Permission denied on port 9000
```bash
# Solution: Use different port
python manage.py runserver 8000
```

## 📚 Next Steps

- Read the [Complete Installation Guide](./INSTALLATION.md)
- Explore [Platform Features](../guides/FEATURES.md)
- Check out the [ChEMBL Import Guide](../guides/CHEMBL_IMPORT_GUIDE.md)
- Review the [API Documentation](../api/API_DOCUMENTATION.md)

## 🆘 Need Help?

- **Documentation**: [Full Documentation](../README.md)
- **Issues**: [GitHub Issues](https://github.com/PedroVictorCoding/neurobin/issues)
- **Community**: [GitHub Discussions](https://github.com/PedroVictorCoding/neurobin/discussions)

---
*For production deployment, see the [Deployment Guide](./DEPLOYMENT.md)*
