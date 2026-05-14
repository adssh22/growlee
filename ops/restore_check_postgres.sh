#!/usr/bin/env bash
set -euo pipefail
: "${RESTORE_DATABASE_URL:?RESTORE_DATABASE_URL is required. Use an empty throwaway database, never production.}"
: "${BACKUP_FILE:?BACKUP_FILE is required}"
pg_restore --clean --if-exists --no-owner --no-acl --dbname="$RESTORE_DATABASE_URL" "$BACKUP_FILE"
printf 'Restore check completed against %s\n' "$RESTORE_DATABASE_URL"
