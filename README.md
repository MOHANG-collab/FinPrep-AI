# FinPrep AI — Full-Stack Financial Data Preprocessing MVP

A runnable full-stack web application using **HTML, CSS, JavaScript, FastAPI, Pandas, SQLAlchemy**, with optional **Supabase PostgreSQL and private Supabase Storage**.

## Included and working

- Landing page, registration, login, session cookie and protected dashboard
- CSV/XLSX uploads, preview and data-quality profiling
- Missing-value handling, exact duplicate removal and date standardization
- Preview changes before saving; original upload is preserved
- Analytics with Chart.js (numeric totals, monthly/category breakdowns)
- Saved processing history and CSV/XLSX/PDF downloads
- Database models for users, datasets, processing jobs and audit logs
- Local development defaults; online database/storage configuration available
- Synthetic sample dataset

## Important scope notes

This is a **functional MVP**, not a fully finished enterprise SaaS. Razorpay checkout, subscriptions, quotas, team roles, comprehensive audit exports, migrations, CSRF hardening, antivirus scanning, and production-grade asynchronous processing are **not implemented**. Pricing page explicitly labels future plans. PDF report is a basic summary. Financial totals are not equivalent to profit. Do not use real confidential financial data before a security review.

## Local setup

1. Install Python 3.11 or newer.
2. Create a virtual environment:
   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate
   # macOS/Linux: source .venv/bin/activate
   ```
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env`.
5. Replace `JWT_SECRET` with a long random string (e.g. `python -c "import secrets;print(secrets.token_urlsafe(48))"`).
6. Run: `uvicorn backend.main:app --reload`
7. Open **http://127.0.0.1:8000**.
8. Register, log in and upload `sample_data/sample_transactions.csv`.

Without cloud credentials, SQLite and local file storage are used for development. These are **not** durable on most free cloud hosts.

## Set up a fully online database and file storage

1. Create a Supabase project at https://supabase.com/dashboard.
2. Obtain the PostgreSQL connection string from Supabase's database connection settings (use the pooler if required by your host). Use a URL compatible with `postgresql+psycopg://`.
3. In Supabase Storage, create **private** buckets exactly named `original-datasets` and `processed-datasets`.
4. Set the following environment variables on your server, **not in browser JavaScript**:
   - `DATABASE_URL=postgresql+psycopg://...`
   - `SUPABASE_URL=https://YOUR_PROJECT.supabase.co`
   - `SUPABASE_SERVICE_ROLE_KEY=...` (server-only secret)
   - `JWT_SECRET=...` (long random secret)
   - `COOKIE_SECURE=true` (for HTTPS)
5. Run the application on a Python host. SQLAlchemy will create tables on first startup in this MVP. For production, introduce Alembic migrations and managed backups.
6. Verify registration, upload, processing and download **after redeployment**.

**Never put Supabase service-role keys in the frontend, commit `.env`, or share credentials with evaluators.** Use a separate demo account and synthetic data.

## Deployment (Render or other Python host)

- Push this project to a private or public GitHub repository **without `.env`**.
- Create a Python web service on Render or another host.
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Add the environment variables listed above in the host dashboard.
- Use HTTPS and `COOKIE_SECURE=true`.
- Open the generated public URL and test end-to-end.

**Cloud services are not provisioned automatically by this ZIP.** The supplied code connects to your online Supabase project once you configure its credentials.

## Endpoints

- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- `POST /api/datasets/upload`, `GET /api/datasets`, `GET /api/datasets/{id}/profile`
- `POST /api/datasets/{id}/preview-cleaning`, `POST /api/datasets/{id}/process`
- `GET /api/datasets/{id}/analytics`, `GET /api/history`
- `GET /api/jobs/{id}/download?format=csv|xlsx|pdf`
- `GET /api/dashboard`

Interactive API documentation: `/docs`.

## Submission checklist

- Deploy with Supabase DB and storage, set secure secrets.
- Register a demo account and upload synthetic data.
- Verify browser workflows and refresh persistence.
- Share the public URL, source repository and demo credentials (not server secrets).

## Security limitations

For a real production financial service, add CSRF protection for cookie-authenticated state-changing routes, rate limiting, malware scanning, comprehensive file-content validation, security monitoring, durable job queues, database migrations, account recovery, data retention controls and a privacy policy. The demo intentionally avoids real payments.
