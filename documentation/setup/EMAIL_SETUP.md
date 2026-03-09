# Email Verification Setup

This project now supports email verification on registration.

## 1) Local SMTP service (own ports)

Start Mailpit from the repo root:

```bash
docker compose -f docker-compose.email.yml up -d
```

Mailpit ports:
- `1025` SMTP server
- `8025` inbox UI (`http://localhost:8025`)

## 2) Environment variables

Set these in `.env` (or your deployment secrets):

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=127.0.0.1
EMAIL_PORT=1025
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=false
EMAIL_USE_SSL=false
DEFAULT_FROM_EMAIL=Neurobin <no-reply@your-domain.com>
EMAIL_DELIVERY_ASYNC=false
EMAIL_VERIFICATION_TOKEN_TTL_HOURS=24
```

For production, set `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, and `EMAIL_HOST_PASSWORD` to your SMTP provider values.

## 3) Cloudflare note

Cloudflare handles DNS/routing but does not send outbound SMTP by itself.  
You still need an SMTP provider (SES, Postmark, Resend SMTP, Mailgun, etc.) and should publish SPF/DKIM/DMARC on your domain.

## 4) Optional async delivery service

If you already run Redis + Celery:

```env
EMAIL_DELIVERY_ASYNC=true
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
```

Then run a worker:

```bash
cd core
../venv/bin/celery -A core worker -l info
```
