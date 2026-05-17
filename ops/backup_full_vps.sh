#!/usr/bin/env bash
set -euo pipefail

BACKUP_ROOT="${FULL_BACKUP_ROOT:-/var/backups/growlee/full}"
RETENTION_DAYS="${FULL_BACKUP_RETENTION_DAYS:-30}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
BACKUP_HELPER_IMAGE="${BACKUP_HELPER_IMAGE:-alpine:3.20}"

log() {
  printf '[backup-full] %s\n' "$*"
}

warn() {
  printf '[backup-full] warning: %s\n' "$*" >&2
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[backup-full] error: missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

run_compose() {
  if [[ -f "$ENV_FILE" ]]; then
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
  else
    docker compose -f "$COMPOSE_FILE" "$@"
  fi
}

compose_project_name() {
  run_compose config --format json 2>/dev/null | sed -n 's/^  "name": "\([^"]*\)",$/\1/p' | head -n 1
}

copy_volume_by_name_if_exists() {
  local volume_name="$1"
  local destination="$2"
  local label="$3"

  if [[ -z "$volume_name" ]] || ! docker volume inspect "$volume_name" >/dev/null 2>&1; then
    return 1
  fi

  mkdir -p "$destination"
  if docker run --rm \
    -v "$volume_name:/source:ro" \
    -v "$destination:/backup-destination" \
    "$BACKUP_HELPER_IMAGE" \
    sh -c 'cd /source && tar -cf - . | tar -xf - -C /backup-destination' >/dev/null 2>&1; then
    log "Saved $label"
    return 0
  fi

  rm -rf --one-file-system "$destination"
  return 1
}

copy_from_container_or_volume_if_possible() {
  local service="$1"
  local source_path="$2"
  local destination="$3"
  local label="$4"
  local volume_short_name="${5:-}"
  local container_id project_name volume_name

  container_id="$(run_compose ps -q "$service" 2>/dev/null || true)"
  if [[ -n "$container_id" ]]; then
    mkdir -p "$(dirname "$destination")"
    if docker cp "$container_id:$source_path" "$destination" >/dev/null 2>&1; then
      log "Saved $label"
      return 0
    fi
    warn "could not copy $label from service '$service' ($source_path); trying Docker volume fallback"
  fi

  if [[ -n "$volume_short_name" ]]; then
    project_name="$(compose_project_name || true)"
    volume_name="${project_name}_${volume_short_name}"
    if copy_volume_by_name_if_exists "$volume_name" "$destination" "$label"; then
      return 0
    fi
  fi

  warn "could not save $label; skipped"
}

write_metadata() {
  local metadata_file="$1"

  {
    printf 'date_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'git_commit=%s\n' "$(git rev-parse HEAD 2>/dev/null || printf 'unknown')"
    printf 'git_branch=%s\n' "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown')"
    printf '\n[docker compose ps]\n'
    run_compose ps 2>&1 || true
    printf '\n[docker compose images]\n'
    run_compose images 2>&1 || true
    printf '\n[docker compose config images]\n'
    run_compose config --images 2>&1 || true
  } > "$metadata_file"
}

cleanup_stage() {
  if [[ -n "${STAGE_DIR:-}" && -d "${STAGE_DIR:-}" ]]; then
    rm -rf --one-file-system "$STAGE_DIR"
  fi
}

main() {
  if [[ ! -f "$COMPOSE_FILE" ]]; then
    printf '[backup-full] error: run this script from the repository root; missing %s\n' "$COMPOSE_FILE" >&2
    exit 1
  fi

  require_cmd docker
  require_cmd git
  require_cmd tar
  require_cmd sha256sum
  require_cmd find

  if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
    printf '[backup-full] error: FULL_BACKUP_RETENTION_DAYS must be a non-negative integer\n' >&2
    exit 1
  fi

  local stamp archive
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  STAGE_DIR="$BACKUP_ROOT/$stamp"
  archive="$BACKUP_ROOT/growlee-full-$stamp.tar.gz"

  if ! mkdir -p "$STAGE_DIR"; then
    printf '[backup-full] error: cannot create backup directory %s (run with sufficient permissions or set FULL_BACKUP_ROOT)\n' "$STAGE_DIR" >&2
    exit 1
  fi
  chmod 700 "$BACKUP_ROOT" "$STAGE_DIR"
  trap cleanup_stage EXIT

  log "Starting full backup $stamp"
  log "Checking PostgreSQL availability"
  if ! run_compose exec -T db sh -c 'pg_isready -U "${POSTGRES_USER:-growlee}" -d "${POSTGRES_DB:-growlee}" >/dev/null'; then
    printf '[backup-full] error: PostgreSQL is not accessible via docker compose service db\n' >&2
    exit 1
  fi

  log "Dumping PostgreSQL"
  if ! run_compose exec -T db sh -c 'pg_dump -U "${POSTGRES_USER:-growlee}" -d "${POSTGRES_DB:-growlee}" --format=custom --no-owner --no-acl' > "$STAGE_DIR/postgres.dump"; then
    printf '[backup-full] error: PostgreSQL dump failed\n' >&2
    exit 1
  fi

  if [[ -f "$ENV_FILE" ]]; then
    install -m 600 "$ENV_FILE" "$STAGE_DIR/.env.prod"
    log "Saved .env.prod"
  else
    warn "$ENV_FILE not found; skipped environment file"
  fi

  if [[ -f deploy/Caddyfile ]]; then
    install -m 644 deploy/Caddyfile "$STAGE_DIR/Caddyfile"
    log "Saved deploy/Caddyfile"
  else
    warn "deploy/Caddyfile not found; skipped"
  fi

  copy_from_container_or_volume_if_possible web /app/media "$STAGE_DIR/media_data" media_data media_data
  copy_from_container_or_volume_if_possible caddy /data "$STAGE_DIR/caddy_data" caddy_data caddy_data
  copy_from_container_or_volume_if_possible caddy /config "$STAGE_DIR/caddy_config" caddy_config caddy_config

  write_metadata "$STAGE_DIR/metadata.txt"
  log "Saved metadata.txt"

  log "Creating archive"
  tar -C "$BACKUP_ROOT" -czf "$archive" "$stamp"
  chmod 600 "$archive"
  sha256sum "$archive" > "$archive.sha256"
  chmod 600 "$archive.sha256"

  log "Applying retention: ${RETENTION_DAYS} day(s)"
  find "$BACKUP_ROOT" -maxdepth 1 -type f \( -name 'growlee-full-*.tar.gz' -o -name 'growlee-full-*.tar.gz.sha256' \) -mtime +"$RETENTION_DAYS" -delete
  find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '????????T??????Z' -mtime +"$RETENTION_DAYS" -exec rm -rf --one-file-system {} +

  trap - EXIT
  cleanup_stage

  log "Backup archive: $archive"
  log "SHA256 file: $archive.sha256"
}

main "$@"
