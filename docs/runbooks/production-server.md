# Production server runbook

This runbook describes the approved production shape. It does not install or select a web server.

## Architecture

- Run one backend server with a permanent disk.
- Host the frontend on Vercel.
- Use Supabase PostgreSQL through `DATABASE_URL`.
- Keep encrypted private uploads on the permanent disk under `PRIVATE_MEDIA_ROOT`.
- Run the web process and `manage.py run_worker` as two long-running processes supervised by the service manager.

## Web server — PENDING OWNER DECISION

Django's `runserver` must not be used in production. The owner must approve either a pinned Gunicorn version for Linux or a pinned Waitress version for Windows before production setup can finish. Do not install either server until that decision and exact version pin are recorded.

## HTTPS and proxying

Terminate HTTPS at a reverse proxy and forward requests to the backend web process. Set `DJANGO_TRUST_PROXY=1` only when the backend is actually behind that trusted proxy. Do not expose the private upload directory through the proxy or Django static/media routes.

## File and key backups

- `PRIVATE_MEDIA_ROOT` must be on the permanent server disk and must never be served directly.
- Supabase provides the database backup service for the production PostgreSQL database.
- Back up the encrypted private-media data daily.
- Back up `FILE_ENCRYPTION_KEY` separately from both the database and encrypted files. Without that key, encrypted uploads cannot be recovered.

## Release order

1. Deploy the reviewed application release.
2. Run `manage.py migrate` against the configured database.
3. Restart the web server process.
4. Restart the `manage.py run_worker` process.
5. Verify `/healthz` and `/readyz`, then inspect worker health before accepting traffic.

## Operational boundaries

The Vercel-hosted backend is for testing or demonstration only and must never store real customer uploads. Production uploads and the worker run on the server with permanent disk storage.
Rate limits are counted independently per web-server process because the ratelimit cache is process-local.
