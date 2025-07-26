# ChemBio Importer Installation Guide

## Prerequisites

- Python 3.8 or higher
- pip package manager
- Internet connection for API access

## Installation Methods

### Method 1: From Source (Recommended)

1. **Clone or download the repository:**
   ```bash
   cd /path/to/your/projects
   # If you have the source code already, skip this step
   ```

2. **Navigate to the project directory:**
   ```bash
   cd data_aggregator
   ```

3. **Create a virtual environment (recommended):**
   ```bash
   python -m venv chembio_env
   source chembio_env/bin/activate  # On Windows: chembio_env\Scripts\activate
   ```

4. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Install the package in development mode:**
   ```bash
   pip install -e .
   ```

### Method 2: Direct Installation

```bash
pip install -r requirements.txt
```

## Dependencies

The package requires the following main dependencies:

- **chembl_webresource_client** - ChEMBL API access
- **sqlalchemy** - Database ORM
- **requests** - HTTP client
- **click** - CLI interface
- **tqdm** - Progress bars
- **pandas** - Data manipulation
- **rdkit** - Chemical informatics
- **psycopg2-binary** - PostgreSQL support (optional)

## Database Setup

### SQLite (Default)

SQLite is used by default and requires no additional setup. The database file will be created automatically.

### PostgreSQL (Optional)

For production use, PostgreSQL is recommended:

1. **Install PostgreSQL server**
2. **Create database:**
   ```sql
   CREATE DATABASE chembio_db;
   CREATE USER chembio_user WITH PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE chembio_db TO chembio_user;
   ```

3. **Configure environment variables:**
   ```bash
   export DATABASE_URL="postgresql://chembio_user:your_password@localhost:5432/chembio_db"
   ```

## Configuration

### Environment Variables

Create a `.env` file in the project root (copy from `.env.example`):

```bash
# Database configuration
DATABASE_URL=sqlite:///chem_react.db
DATABASE_ECHO=false

# Logging
LOG_LEVEL=INFO
LOG_FILE=chembio_importer.log

# API rate limiting
SLOW_MODE=true
SLEEP_INTERVAL=2
```

### Configuration File

Key settings in `chembio_importer/config.py`:

```python
# API Settings
CHEMBL_BATCH_SIZE = 50
REACTOME_BASE_URL = "https://reactome.org/ContentService/"

# Rate limiting
SLOW_MODE = True
SLEEP_INTERVAL = 2

# Database
DATABASE_URL = "sqlite:///chem_react.db"
```

## Verification

Test the installation:

```bash
# Test CLI access
python -m chembio_importer --help

# Test basic functionality
python examples/basic_usage.py

# Initialize database
python -m chembio_importer --init-db
```

## Common Installation Issues

### Issue: RDKit Installation Problems

**Solution:** RDKit can be challenging to install. Try:

```bash
# Option 1: Use conda
conda install -c conda-forge rdkit

# Option 2: Use conda-forge channel with pip
pip install rdkit-pypi

# Option 3: Skip RDKit (some features will be disabled)
# Comment out rdkit lines in requirements.txt
```

### Issue: ChEMBL Client Import Error

**Solution:** Ensure you have the latest version:

```bash
pip install --upgrade chembl_webresource_client
```

### Issue: Database Permission Errors

**Solution:** Check database permissions and paths:

```bash
# For SQLite
touch chem_react.db
chmod 666 chem_react.db

# For PostgreSQL
# Ensure user has proper database permissions
```

### Issue: API Connection Problems

**Solution:** Test network connectivity:

```bash
# Test ChEMBL API
curl "https://www.ebi.ac.uk/chembl/api/data/molecule/CHEMBL25"

# Test Reactome API
curl "https://reactome.org/ContentService/data/pathways/low/entity/P04637"
```

## Performance Optimization

### For Large Imports

1. **Use PostgreSQL instead of SQLite**
2. **Increase batch sizes** (but respect API limits)
3. **Enable slow mode** to avoid API bans
4. **Monitor disk space** for large databases

### Memory Management

```python
# Configure SQLAlchemy for large datasets
DATABASE_URL = "postgresql://user:pass@localhost/db?pool_size=20&max_overflow=0"
```

## Updating

To update the package:

```bash
# Pull latest changes
git pull

# Update dependencies
pip install -r requirements.txt --upgrade

# Reinstall package
pip install -e .
```

## Uninstallation

```bash
# Remove virtual environment
deactivate
rm -rf chembio_env

# Or just uninstall the package
pip uninstall chembio-importer
```

## Next Steps

After installation:

1. **Read the [Usage Guide](USAGE.md)**
2. **Try the [Examples](../examples/)**
3. **Check the [API Reference](API.md)**
4. **Run your first import:**
   ```bash
   python -m chembio_importer --from-chembl --limit 100 --slow
   ```
