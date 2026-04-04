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
export DB_PASSWORD=<your-password>
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

## Cloud Relay Sync (Cron Job)

The internal server polls the cloud relay periodically to import work logs.

### Manual Testing

```bash
cd internal_server
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Dry run (show what would be imported)
python manage.py sync_relay --dry-run

# Force sync from beginning (ignores last_sync timestamp)
python manage.py sync_relay --force-sync

# Normal sync
python manage.py sync_relay
```

### Required Environment Variables

```bash
export CLOUD_RELAY_BASE_URL=https://horticulture-relay.your-domain.workers.dev
export CLOUD_RELAY_POLL_TOKEN=your-poll-token
```

### Cron Configuration

Add to crontab (`crontab -e`) to sync every 10 minutes:

```cron
*/10 * * * * cd /path/to/internal_server && ./venv/bin/python manage.py sync_relay >> /var/log/sync_relay.log 2>&1
```

For verbose cron logging (recommended):

```cron
*/10 * * * * cd /path/to/internal_server && ./venv/bin/python manage.py sync_relay --verbosity 2 >> /var/log/sync_relay.log 2>&1
```

### Log Output Example

```
Starting cloud relay sync...
Last sync timestamp: 2026-04-04 10:30:00+00:00
Fetching pending uploads from https://horticulture-relay.your-domain.workers.dev
Found 5 pending records
[1/5] Processing record...
  Created worker: John Doe (EMP001)
  Imported: relay-abc123
[2/5] Processing record...
  Skipped: Duplicate relay_id: relay-abc124
...
==================================================
Sync completed!
  Total records: 5
  Imported: 4
  Skipped: 1
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
