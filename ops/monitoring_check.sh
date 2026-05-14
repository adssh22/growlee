#!/usr/bin/env bash
set -euo pipefail
DOMAIN="${DOMAIN:-growlee.fr}"
WARN_DAYS="${SSL_WARN_DAYS:-21}"
printf '== disk ==\n'; df -h /
printf '\n== memory ==\n'; free -m || true
printf '\n== load ==\n'; uptime
printf '\n== postgres size ==\n'
if [[ -n "${DATABASE_URL:-}" ]]; then
  psql "$DATABASE_URL" -Atc "select pg_size_pretty(pg_database_size(current_database()));" || true
else
  echo 'DATABASE_URL not set, skipping DB size'
fi
printf '\n== ssl expiry ==\n'
end_date=$(echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null | openssl x509 -noout -enddate | cut -d= -f2 || true)
if [[ -n "$end_date" ]]; then
  end_epoch=$(date -d "$end_date" +%s)
  now_epoch=$(date -u +%s)
  days=$(( (end_epoch - now_epoch) / 86400 ))
  echo "$DOMAIN expires in $days days ($end_date)"
  if (( days < WARN_DAYS )); then exit 2; fi
else
  echo 'Could not read certificate'; exit 1
fi
