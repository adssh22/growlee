#!/usr/bin/env bash
set -euo pipefail
: "${DATABASE_URL:?DATABASE_URL is required}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/growlee/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$BACKUP_DIR/growlee-$stamp.dump"
pg_dump "$DATABASE_URL" --format=custom --no-owner --no-acl --file="$out"
sha256sum "$out" > "$out.sha256"
find "$BACKUP_DIR" -type f \( -name '*.dump' -o -name '*.sha256' \) -mtime +"$RETENTION_DAYS" -delete
printf 'Backup written: %s\n' "$out"
