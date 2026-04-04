# Cloud Relay API

Base URL: `https://horticulture-relay.your-domain.workers.dev`

## POST /api/upload

Upload work log from mobile app.

### Request

```json
{
  "zone_id": "zone-001",
  "worker_id": "worker-123",
  "work_type": "irrigation_repair",
  "work_order": "WO-2024-001",
  "notes": "Fixed leak in sector 3",
  "timestamp": "2024-04-04T10:30:00Z",
  "gps": {
    "latitude": 40.7128,
    "longitude": -74.0060
  }
}
```

### Response

```json
{
  "success": true,
  "id": "1712232600-abc123def"
}
```

## GET /api/pending-uploads

Poll for unprocessed work logs (internal server only).

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `last_sync` | string | ISO timestamp of last sync |

### Response

```json
{
  "records": [
    {
      "id": "1712232600-abc123def",
      "zone_id": "zone-001",
      "worker_id": "worker-123",
      "work_type": "irrigation_repair",
      "work_order": "WO-2024-001",
      "notes": "Fixed leak in sector 3",
      "timestamp": "2024-04-04T10:30:00Z",
      "uploaded_at": "2024-04-04T10:31:00Z",
      "processed": false,
      "gps": {
        "latitude": 40.7128,
        "longitude": -74.0060
      }
    }
  ]
}
```
