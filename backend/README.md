# Dristi-Scan Backend

FastAPI-based security scanning backend for Dristi-Scan.

## Quickstart (local)
1. Create virtualenv and install deps:
   ```bash
   python -m venv .venv && .venv\Scripts\activate
   pip install -r backend/requirements.txt
   ```
2. Set environment (examples):
   ```
   export DATABASE_URL=postgresql://admin:adminpassword@localhost:5432/drishtiscan
   export SECRET_KEY=supersecretkey_change_in_production
   export ACCESS_TOKEN_EXPIRE_MINUTES=60
   ```
3. Run API:
   ```bash
   uvicorn app.main:app --reload
   ```

## Docker
- Build & run everything:
  ```bash
  docker-compose up --build
  ```
- Backend image exposes `8000`.

## Vulnerability Rule Engine
- Central library: `backend/rules/vulnerability_rules.json` (113 regex rules spanning Injection, Secrets exposure, Cryptography issues, File system vulnerabilities, Command execution risks, Web vulnerabilities, Authentication flaws).
- Rule schema: `name`, `category`, `severity`, `pattern` (regex), `description`, `remediation`, optional `cwe_reference`.
- Rules are compiled once on startup and scanned line-by-line; edit the JSON and restart the API to reload.
- Example:
  ```json
  { "name": "SQL Concatenation Injection", "category": "Injection", "severity": "Critical", "pattern": "(?i)select\\s+.*from\\s+.*\\+.*", "description": "SQL built via string concatenation.", "remediation": "Use parameterized queries or ORM placeholders." }
  ```

## Core Endpoints
- `POST /auth/register` – body `{ "email": "...", "password": "..." }`
- `POST /auth/login` – body `{ "email": "...", "password": "..." }`
- `GET /auth/profile` – `Authorization: Bearer <token>`
- `POST /scan/code` – body `{ "code": "<string>", "file_name": "example.py" }`
- `POST /scan/upload` – multipart file upload (`file` field)
- `GET /reports/{scan_id}` – structured report JSON
- `GET /reports/{scan_id}/pdf` – downloadable PDF
- `GET /reports/history` – latest scans for the current user

## Example cURL
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"Password123"}' | jq -r .access_token)

curl -X POST http://localhost:8000/scan/code \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"code":"import os\\nos.system(input())","file_name":"example.py"}'
```
