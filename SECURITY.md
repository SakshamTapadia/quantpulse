# Security Policy

## Default Credentials

This project ships with **development-only** default credentials. **Change all of these before any public deployment.**

| Variable | Default | Action Required |
|----------|---------|----------------|
| `POSTGRES_PASSWORD` | `changeme` | Set a strong password in `.env` |
| `REDIS_PASSWORD` | `changeme` | Set a strong password in `.env` |
| `JWT_SECRET` | `changeme_use_openssl_rand` | Generate: `openssl rand -base64 32` |
| Grafana admin | `changeme` | Change via `GF_SECURITY_ADMIN_PASSWORD` |

## API Keys

Never commit your `.env` file. The `.gitignore` already excludes it.

- **POLYGON_API_KEY** — Keep private, rotate if exposed
- **FRED_API_KEY** — Keep private, rotate if exposed

## Demo Authentication

The API gateway ships in **demo mode**: any non-empty username/password is accepted.
For production, replace the auth handler in `services/api/src/quantpulse_api/app.py`
with a proper user database or OAuth provider.

## Reporting a Vulnerability

Open a GitHub issue marked **[SECURITY]** or email the maintainer directly.
Please do not disclose security vulnerabilities publicly until they have been addressed.
