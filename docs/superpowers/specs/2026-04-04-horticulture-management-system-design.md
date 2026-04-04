# Horticulture Management System - Design Specification

**Date:** 2026-04-04  
**Status:** Approved

---

## 1. Overview

Build an online horticulture management system to replace/augment the local Maxicom software provided by Rain Bird. The system enables field workers to upload irrigation work data via a mobile app, with data synchronized to an internal server for management and reporting.

---

## 2. Architecture

### 2.1 High-Level Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                         FIELD WORKER                               │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Android App (React Native)                                 │  │
│  │  - Map view with zone polygons                              │  │
│  │  - GPS positioning                                          │  │
│  │  - Click zone → enter work order, notes, timestamp          │  │
│  │  - Uploads to cloud relay (cellular data)                   │  │
│  │  - Queues locally if offline                                │  │
│  └─────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS (cellular/internet)
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│                      CLOUD RELAY (Public)                          │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Phase 1: Cloudflare Workers (Free tier)                    │  │
│  │  - POST /api/upload  (mobile app uploads)                   │  │
│  │  - GET /api/pending-uploads  (internal server polls)        │  │
│  │  - KV Storage                                               │  │
│  └─────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Phase 2: FastAPI (Future - Render/Railway)                 │  │
│  │  - Complex API operations                                   │  │
│  │  - Data transformation                                      │  │
│  │  - Admin/management endpoints                               │  │
│  └─────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  PostgreSQL (Supabase free tier)                            │  │
│  └─────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS (internal server initiates)
                              │ (polling every 5-15 min)
                              ▼
┌────────────────────────────────────────────────────────────────────┐
│                    INTERNAL SERVER (Company WiFi)                  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Django + Django REST Framework                             │  │
│  │  - Admin panel for management                               │  │
│  │  - REST API for frontend + mobile                           │  │
│  │  - Cron job: Poll cloud relay                               │  │
│  │  - Cron job: Import Maxicom exports                         │  │
│  └─────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  PostgreSQL / MySQL                                         │  │
│  │  - Zones, plants, work orders, workers, events              │  │
│  └─────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │  Frontend Dashboard                                         │  │
│  │  - Zone status dashboard                                    │  │
│  │  - Interactive map (Leaflet)                                │  │
│  │  - Satellite/base map toggle                                │  │
│  │  - Work orders, assignments                                 │  │
│  └─────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. Components

### 3.1 Mobile App (React Native)

**Technology:** React Native with react-native-maps

**Features:**
- Map view displaying irrigation zone polygons
- Real-time GPS positioning
- Zone selection (tap/click)
- Work order entry form:
  - Work type
  - Notes
  - Automatic timestamp
  - Worker identification
- Offline queue (local storage)
- Sync to cloud relay when connected

**Map Features:**
- Satellite and standard map toggle
- Pre-defined zone boundaries
- Visual zone highlighting on hover/tap
- Proximity detection (highlight nearby zones)

---

### 3.2 Cloud Relay

**Phase 1: Cloudflare Worker**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload` | POST | Mobile app uploads work data |
| `/api/pending-uploads` | GET | Internal server polls for new data |

**Storage:** Cloudflare KV (free tier: 100K reads/day, 1K writes/day)

**Phase 2: FastAPI (Future)**

- Deploy on Render or Railway (~$5-10/month)
- Connect to PostgreSQL (Supabase free tier)
- Extended API endpoints for:
  - Data validation/transformation
  - Third-party integrations
  - Reporting endpoints
  - Admin management

---

### 3.3 Internal Server

**Technology:** Django + Django REST Framework

**Database Models:**
- `Zone` - Irrigation zones with polygon boundaries
- `Plant` - Plant types per zone
- `WorkOrder` - Scheduled/completed work
- `Worker` - Field staff
- `Event` - Special events affecting irrigation
- `WorkLog` - Completed work entries from mobile app

**Key Features:**
- Django Admin for data management
- REST API for frontend and mobile
- Cron jobs:
  - Poll cloud relay (every 5-15 min)
  - Import Maxicom database exports

**Frontend Dashboard:**
- Zone status overview (irrigation status: done/working/scheduled/canceled/delayed)
- Plant information per zone
- Worker assignments
- Interactive map (Leaflet.js)
  - Satellite/base map toggle
  - Zone polygons with hover details
  - Work order overlays

---

## 4. Data Flow

### 4.1 Mobile Upload Flow

1. Worker completes task in field
2. App saves work log locally (SQLite/AsyncStorage)
3. App uploads to Cloudflare Worker `POST /api/upload`
4. Cloudflare Worker stores in KV/PostgreSQL
5. If upload fails, data remains queued locally

### 4.2 Internal Sync Flow

1. Internal server cron runs (every 5-15 min)
2. Django management command calls `GET /api/pending-uploads?last_sync=<timestamp>`
3. Cloudflare Worker returns unprocessed records
4. Django imports records into internal database
5. Marks records as processed on relay

### 4.3 Maxicom Import Flow

1. Export database from Maxicom (manual/automated)
2. Django management command parses export file
3. Imports/updates zones, schedules, configuration
4. Merges with mobile work log data

---

## 5. Security Considerations

### 5.1 Cloud Relay Authentication

- Mobile app: API key or token-based auth
- Internal server polling: Separate service token
- Rate limiting on all endpoints

### 5.2 Internal Server Security

- Company WiFi only access for frontend
- Mobile app and relay use token authentication
- Django's built-in CSRF protection
- Database access restricted to application

### 5.3 Data Privacy

- Worker location data only stored when actively logging work
- No continuous GPS tracking
- Data retention policy for work logs

---

## 6. Error Handling

### 6.1 Mobile App

- Network failures → queue locally, retry on next connection
- Invalid zone data → show error, allow manual zone selection
- Sync conflicts → timestamp-based resolution

### 6.2 Cloud Relay

- Worker errors → return 5xx, client retries
- KV quota exceeded → alert admin, queue on client

### 6.3 Internal Server

- Relay polling fails → log error, retry on next cron
- Import failures → transaction rollback, alert admin

---

## 7. Testing Strategy

### 7.1 Backend (Django)

- Unit tests for models and API endpoints
- Integration tests for relay sync
- Management command tests for Maxicom import

### 7.2 Mobile App

- Component tests for UI elements
- Integration tests for sync flow
- Manual testing for GPS/map features

### 7.3 Cloud Relay

- Unit tests for Worker handlers
- Integration tests with mock mobile/internal server

---

## 8. Deployment

### 8.1 Internal Server

- Deploy on company infrastructure
- IT manages SSL certificates, firewall rules
- Django served via Gunicorn + Nginx
- PostgreSQL/MySQL database

### 8.2 Cloud Relay

- Phase 1: Cloudflare Workers (deploy via Wrangler CLI)
- Phase 2: FastAPI on Render/Railway
- PostgreSQL on Supabase free tier

### 8.3 Mobile App

- APK distribution (internal company distribution)
- Or Google Play Store (private channel)

---

## 9. Future Enhancements

- Push notifications for work assignments
- Photo attachments for work logs
- Barcode/QR scanning for equipment
- Offline map tiles for remote areas
- iOS version (React Native cross-platform)
- Analytics dashboard for management

---

## 10. Open Questions

1. **Maxicom export format** - Need to confirm file format (CSV, SQLite, proprietary?)
2. **Zone boundary data** - Manual drawing tool requirements
3. **User authentication** - Integration with existing company SSO?
4. **Polling interval** - Confirm acceptable latency (5, 10, 15 minutes?)

---

## 11. Acceptance Criteria

- [ ] Workers can upload work logs from the field via mobile app
- [ ] Data syncs to internal server within polling interval
- [ ] Dashboard displays zone status and map with zone polygons
- [ ] Map supports satellite/base layer toggle
- [ ] System works offline (local queue, sync when connected)
- [ ] Internal server initiates all external connections (pull model)
- [ ] Cloud relay on free tier (Cloudflare Workers)
- [ ] FastAPI interface ready for future expansion
