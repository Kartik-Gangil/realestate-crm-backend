# Railway UAT Backend Runbook

Task: `TASK-INFRA-002`  
Environment: UAT only; demo/UAT data only  
Database: owner-provided Supabase PostgreSQL database

This runbook deploys the Django backend for UAT validation. It is not the approved production hosting shape. Railway storage is treated as non-durable: do not enter real customer data, production secrets, or real customer uploads.

## Services

Create or select a Railway project and UAT environment with two services sourced from the `Kartik-Gangil/realestate-crm-backend` GitHub repository on the approved `main` commit:

- Web service: use `/railway.json` and expose the generated Railway domain only to the configured UAT frontend.
- Worker service: use `/railway.worker.json` as the service's custom Railway config path. It runs the existing `python manage.py run_worker` command.

Railway supports repository-backed services, config-as-code files, pre-deploy commands, and healthchecks. Configure the worker's custom config path in its service settings so the web service and worker use different start commands.

## Required Railway variables

Add these as Railway environment/service variables. Values are supplied through the Railway variable editor or secret manager and must never be committed here:

| Variable | UAT value or rule |
|---|---|
| `DATABASE_URL` | Supabase PostgreSQL UAT connection string |
| `DJANGO_SECRET_KEY` | Dedicated UAT value, separate from local and production |
| `INTEGRATION_ENCRYPTION_KEY` | Dedicated UAT key |
| `FILE_ENCRYPTION_KEY` | Dedicated UAT key |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_ALLOWED_HOSTS` | Railway generated host and `healthcheck.railway.app` |
| `CORS_ALLOWED_ORIGINS` | Exact UAT frontend origin, no trailing slash |
| `CSRF_TRUSTED_ORIGINS` | Exact UAT frontend origin with scheme |
| `ENVIRONMENT_NAME` | `uat` |

Set any existing required SMTP/Firebase variables using UAT-only credentials. Do not paste values into this runbook, Git, build logs, or chat messages. `PORT` is provided by Railway and must not be hardcoded.

The effective UAT setting must include `DJANGO_DEBUG=false`; do not enable debug to diagnose a deployment.

## Deploy and verify

1. Confirm the target GitHub commit and that the Backend tests pass for the release.
2. Add the variables above and review Railway's staged changes before deployment.
3. Deploy the web service. Railway runs `python manage.py migrate --noinput` before starting Gunicorn.
4. Deploy the worker service using `/railway.worker.json`.
5. Verify the generated UAT URL returns successful responses from `/healthz` and `/readyz`.
6. Verify Railway logs show Gunicorn listening on Railway's `PORT` and the worker running without printing credentials or request bodies.
7. Run the controlled UAT smoke test against a `demo-` or `uat-` organization only. Confirm login, one read-only project request, and one database-backed worker task.
8. Confirm no real customer data or uploads were used.

## Rollback

Use Railway's deployment history to redeploy the previous known-good Backend commit for both web and worker services. Re-run `/healthz`, `/readyz`, the worker smoke test, and the UAT login check. Do not reset or delete the Supabase database during rollback; migrations require an explicit forward-compatible recovery plan.

## Exit evidence

Record the Railway project/environment/service names, deployed commit SHAs, deployment IDs, healthcheck results, migration result, worker smoke-test result, and rollback verification in the UAT release record. Never record variable values or credentials.
