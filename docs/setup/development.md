# Development Setup

## Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL 14+
- Cloudflare account (free tier)
- Expo CLI (for mobile dev)

## Internal Server Setup

```bash
cd internal_server
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install django djangorestframework psycopg2-binary

# Set environment variables
export DEBUG=True
export DB_NAME=horticulture
export DB_USER=postgres
export DB_PASSWORD=your-password
export DB_HOST=localhost
export DB_PORT=5432

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run server
python manage.py runserver
```

## Cloud Relay Setup

```bash
cd cloud-relay
npm install

# Login to Cloudflare
npx wrangler login

# Deploy
npx wrangler deploy

# For local development
npx wrangler dev
```

## Mobile App Setup

```bash
cd mobile-app
npm install

# Start Expo
npm start

# Run on Android emulator
npm run android

# Run on iOS simulator
npm run ios
```
