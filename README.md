Live demo: https://prithvirajbchavan.github.io/case-management-simulator/
# Customer Service Case Management Simulator

CRM-style service desk: log cases, categorize, assign, escalate, resolve, close and capture fixes in a knowledge base.
Front end: single-page HTML/JS. Back end: Flask + SQLite (REST API).

## Run
    pip install -r requirements.txt
    python app.py
Open http://127.0.0.1:5000 (the database `cases.db` is created on first run).

## API
| Method | Endpoint | Purpose |
|---|---|---|
| GET | /api/cases?status=&priority=&owner= | List / filter cases |
| GET | /api/cases/<id> | One case with notes |
| POST | /api/cases | Log a case (`title` required) |
| PATCH | /api/cases/<id> | Update status, owner, cat, pri, res |
| POST | /api/cases/<id>/notes | Add a troubleshooting note |
| GET | /api/stats | KPI summary (open, escalated, SLA breached) |
| GET/PUT | /api/state | Whole-state sync used by the UI |

## Data model
cases, notes, assets, software, kb, meta. Cases reference assets and software by ID.
