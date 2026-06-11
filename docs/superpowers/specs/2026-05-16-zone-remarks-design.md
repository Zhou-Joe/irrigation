# Zone Remarks (备注/备注确认) Design

## Overview

Add two new fields to the Zone model for daily inspection remarks by horticulture workers. Workers flag issues; managers confirm and triage them into existing irrigation or equipment maintenance records.

## Data Model

Two new `TextField` fields on Zone (same JSON-in-TextField pattern as existing notes):

- **`remarks`** (备注, verbose_name='备注') — `[{"date": "2026-05-16", "content": "3号区域喷头漏水", "author": "张三"}]`
- **`confirmed_remarks`** (备注确认, verbose_name='备注确认') — `[{"date": "...", "content": "...", "author": "...", "confirm_date": "...", "confirm_reply": "...", "confirm_author": "..."}]`

Migration: add both fields with `default=''` and `blank=True`.

## Workflow

1. **Worker adds remark** → appended to `remarks` JSON array with date, content, author (from logged-in user profile name)
2. **Manager confirms** → entry removed from `remarks`, added to `confirmed_remarks` with confirm_date, confirm_reply, confirm_author
3. **Manager triages** → entry removed from `confirmed_remarks`, stripped to `{date, content}`, appended to either `irrigation_management_notes` or `equipment_maintenance_notes`

## UI (Zone Detail Page)

All interactions via AJAX on the zone detail page (`zone_detail_page.html`):

### Add Remark
- Date input (defaults to today) + content textarea + submit button
- Author auto-filled from user's `ManagerProfile.name` or `WorkerProfile.name`

### Pending Remarks (备注) Section
- Timeline display: date, content, author
- Each entry has a "确认" button (visible to managers only) → inline reply input + confirm button

### Confirmed Remarks (备注确认) Section
- Timeline display: original date/content/author + confirm date/reply/author
- Each entry has two buttons (manager only):
  - "转至灌溉管理记录"
  - "转至设备维护记录"

## Backend Endpoints

All require login. All return JSON responses.

| Endpoint | Method | Params | Action |
|----------|--------|--------|--------|
| `/zone/<id>/remark/add/` | POST | date, content | Append to `remarks` |
| `/zone/<id>/remark/<int:index>/confirm/` | POST | confirm_reply, confirm_author | Move from `remarks` to `confirmed_remarks` |
| `/zone/<id>/remark/<int:index>/move/` | POST | target (irrigation/equipment) | Move from `confirmed_remarks` to target notes field |

Permissions: workers can add remarks; managers can confirm and triage.

## Files to Modify

| File | Change |
|------|--------|
| `core/models.py` | Add `remarks` and `confirmed_remarks` TextFields |
| New migration | Add fields with default='' |
| `core/urls.py` | Add 3 URL patterns |
| `core/views.py` | Add 3 view functions + update `zone_detail_page` context |
| `core/templates/core/zone_detail_page.html` | Add remarks UI sections with AJAX |
