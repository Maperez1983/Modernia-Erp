# AGENTS.md

## Cursor Cloud specific instructions

### What this project is
Single Python app: **Verifika² · CRM/ERP** (Spanish, multi-tenant). It is a `http.server`-based
backend (`web/server.py`) that also serves a static vanilla-JS PWA (`web/`). No Node build step is
needed to run the app. See `web/README.md` and `docs/RENDER.md` for the canonical run/deploy notes.

### Python environment
- Dependencies live in `requirements.txt` and are installed into a local virtualenv at `.venv`
  (the startup update script creates `.venv` and runs `pip install -r requirements.txt`).
- Always invoke Python via the venv, e.g. `.venv/bin/python ...`, not the system `python3`.
- System packages `python3.12-venv`, `poppler-utils`, `tesseract-ocr`, `tesseract-ocr-spa` are
  installed in the VM image (not by the update script). `poppler`/`tesseract` are only needed for the
  optional OCR features; the app runs fine without them.

### Running the app (dev)
```bash
.venv/bin/python web/server.py --db data/erp_dev.sqlite --host 0.0.0.0 --port 8000
```
- Default backend is SQLite (a file). Tables are auto-created on boot. Set `DATABASE_URL`/`POSTGRES_URL`
  to use Postgres instead (not needed for local dev). Health check: `GET /api/health`.
- The repo is public: do NOT commit real `.sqlite` DBs or PII. `data/*.sqlite` is git-ignored.

### Seeding demo data (needed to log in / test)
The committed DBs contain no demo login. Seed a fresh dev DB and capture the printed credentials:
```bash
.venv/bin/python scripts/seed_demo_data.py --db data/erp_dev.sqlite --yes --reset-passwords
```
This creates the `Grupo Modernia (Demo)` workspace, two demo empresas, an `admin` and an `empleado`
user (passwords printed with `--reset-passwords`), and one pending vacation request.

### Login / API gotchas
- The login endpoint is `POST /api/login` and expects the field name `usuario` (not `username`):
  `{"usuario":"admin","password":"..."}`.
- A working end-to-end action for smoke-testing is HR time-tracking: log in as `admin`, enter the
  `Grupo Modernia (Demo)` workspace, open **RRHH → HORARIO**, and click **"Marcar/Fichar entrada"**
  (self clock-in). The equivalent API is `POST /api/workspace_registro_horario_toggle`
  with `{"workspace_id":"<ws>","action":"entrada"}` (self) — persona is resolved from the session.

### Demo-data limitations (do not treat as bugs to fix)
- The **Gestoría** "alta cliente" form requires a hard-coded production company named
  `Fincas Velazquez` that the demo seed does not create, so saving a Gestoría client fails with
  "Workspace de Gestoría no disponible" in a seeded env. Use time-tracking/RRHH flows for smoke tests.
- Seeded RRHH personas may not surface in every RRHH list/tab view; the self clock-in path above works
  regardless.

### Tests
Run the unittest suite from the repo root:
```bash
.venv/bin/python -m unittest discover -s tests -p "test_*.py"
```
- ~276 tests pass. The only failures are the two Playwright e2e modules
  (`test_*_playwright.py`), which require `playwright` + browsers (not installed) and are optional.
- There is no separate lint config; there are no build steps (frontend is static).
