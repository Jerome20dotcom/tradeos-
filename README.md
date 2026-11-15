# TradeOS

TradeOS is a small-business workspace, inventory, customer, and sales app. The browser UI supports isolated workspaces, product pricing and stock, customer contacts, recording sales, and reviewing activity. It runs locally on FastAPI and PostgreSQL.

## One-time setup (Windows, PowerShell, in the backend folder)
1. `py -3.12 -m venv .venv`
2. `.venv\Scripts\Activate.ps1`   (if blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then retry)
3. `pip install -r requirements.txt`
4. `copy .env.example .env`, then open `.env` and fill in:
   - `PG_ADMIN_PASSWORD`: the password you set when installing PostgreSQL
   - `PG_APP_PASSWORD`: a new password for the app's database user
   - `JWT_SECRET`: run `python -c "import secrets; print(secrets.token_urlsafe(48))"` and paste the result
5. `python scripts/setup_db.py`  (creates the databases and tables)

## Run the tests
`pytest -v`

## Run the application
From the `backend` folder, activate the virtual environment and run:

1. `uvicorn app.main:app --reload`
2. Open http://127.0.0.1:8000 in your browser.
3. Click **Continue to your workspace**, create a workspace, add products and stock, then record sales.

The browser app supports creating workspaces, managing products and stock, maintaining a customer directory, recording sales with multiple products, and reviewing sales and workspace activity. A sale snapshots product names and prices, deducts stock atomically, and cannot oversell. API documentation remains available at http://127.0.0.1:8000/docs.

The optional hosted Copilot is available from the workspace menu when `COPILOT_API_KEY` is configured. It can answer workspace questions and prepare product, stock, customer, or sale actions. Every write is validated server-side and requires a user to confirm a five-minute preview; cancellation or expiry leaves data unchanged. The configured provider receives the user's prompt, workspace name, product and customer names and record IDs, product prices/stock, and aggregate recent sales; stored customer email/phone and account credentials are excluded from context. Configure `COPILOT_BASE_URL` and `COPILOT_MODEL` for an OpenAI-compatible Chat Completions provider. Copilot is off when no API key is configured.

Email/password accounts use Argon2id password hashes, 12-character minimum passwords, 30-minute bearer tokens, one-time email-verification links, and one-time password-reset links. Email delivery uses SMTP with STARTTLS. In production, set `PUBLIC_BASE_URL` to the HTTPS app URL and provide `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER` (if required), `SMTP_PASSWORD` (if required), and `SMTP_SENDER`. Account registration stays disabled until email delivery is configured. The local development sign-in is hidden and disabled outside `ENVIRONMENT=development`.

## Deploy to Render
The root `render.yaml` provisions a Render web service and managed PostgreSQL database. The Docker build context is the repository root, and the Dockerfile copies the app from `backend/`; the service runs migrations in Render's pre-deploy step and serves the app after the database is ready.

1. Push this repository to GitHub, then in Render choose **New → Blueprint** and select the repository. If configuring a web service manually, choose the **Docker** runtime, leave **Root Directory** blank, set **Dockerfile Path** to `backend/Dockerfile`, and use the repository root as the **Docker Context Directory**.
2. Provide `PUBLIC_BASE_URL`, `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_SENDER`, and `COPILOT_API_KEY` in Render's secret/environment prompt. Do not put credentials in the repository. Use your final HTTPS app URL for `PUBLIC_BASE_URL` and an SMTP provider that supports STARTTLS on port 587.
3. If Render assigns a different service URL, update `PUBLIC_BASE_URL` to that exact HTTPS URL after the first deploy. Until SMTP and HTTPS are configured, account registration and reset are deliberately disabled.
4. Verify `/health`, register a test account, receive and use the verification email, then create a workspace and test a sale. Keep the database private and configure backups/monitoring in Render.

Before accepting public traffic, configure shared rate limiting/WAF for `/v1/auth/login`, `/v1/auth/register`, `/v1/auth/verification/request`, and `/v1/auth/password-reset/request`. Also configure database backups, monitoring, and alerts. Render deployment cannot be completed from this workspace: it needs this repository pushed to GitHub and your Render account plus real SMTP provider settings.

## Layout
- `app/` the API and browser UI (`app/static/`)
- `migrations/` database changes, applied in order by `scripts/setup_db.py`
- `tests/` isolation, permission, validation and audit tests

## Rules this project follows
No secrets in code (`.env` is git-ignored). Every tenant table has `workspace_id` and row-level security.
The API connects as a restricted role that cannot bypass security or edit the audit log.
