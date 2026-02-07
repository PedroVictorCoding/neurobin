neurobin_minimal

A tiny demo of the original Neurobin project. Includes minimal `accounts`, `compounds`, and `stacks` apps with API endpoints and a simple stacks UI.

How to run:

1) Create a virtualenv and install requirements:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2) Run migrations and start server:

```bash
python manage.py migrate
python manage.py runserver
```

3) Visit http://127.0.0.1:8000/ to see API root and http://127.0.0.1:8000/api/stacks/ for the stacks API.
