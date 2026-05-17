#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
BACKUP_HELPER_IMAGE="${BACKUP_HELPER_IMAGE:-alpine:3.20}"
RESTORE_WORKDIR="${RESTORE_WORKDIR:-/tmp/growlee-restore}"
CONFIRM_PHRASE="RESTORE GROWLEE FROM BACKUP"
DRY_RUN=0
EXTRACT_DIR=""

log() {
  printf '[restore-full] %s\n' "$*"
}

warn() {
  printf '[restore-full] warning: %s\n' "$*" >&2
}

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[restore-full] dry-run: '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

usage() {
  cat <<'USAGE'
Usage:
  BACKUP_ARCHIVE=/path/to/growlee-full-YYYYMMDDTHHMMSSZ.tar.gz ./ops/restore_full_vps.sh [--dry-run]

Options:
  --dry-run  Print the destructive steps without applying them.
  -h, --help Show this help.

Environment:
  BACKUP_ARCHIVE       Required path to the full backup .tar.gz archive.
  COMPOSE_FILE         Compose file to use. Default: docker-compose.prod.yml
  ENV_FILE             Env file to restore/use. Default: .env.prod
  RESTORE_WORKDIR      Extraction workdir. Default: /tmp/growlee-restore
  BACKUP_HELPER_IMAGE  Image used to restore Docker volumes. Default: alpine:3.20

This script stops Docker Compose, restores files/volumes, starts PostgreSQL,
restores the database dump, then starts the full stack. It requires explicit
confirmation before destructive actions.
USAGE
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '[restore-full] error: missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

confirm_or_exit() {
  local prompt="$1"
  local answer

  printf '%s\n' "$prompt" >&2
  printf 'Type exactly "%s" to continue: ' "$CONFIRM_PHRASE" >&2
  read -r answer
  if [[ "$answer" != "$CONFIRM_PHRASE" ]]; then
    printf '[restore-full] aborted by user\n' >&2
    exit 1
  fi
}

compose_args() {
  if [[ -f "$ENV_FILE" ]]; then
    printf '%s\0' docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE"
  else
    printf '%s\0' docker compose -f "$COMPOSE_FILE"
  fi
}

run_compose() {
  local args=()
  while IFS= read -r -d '' arg; do
    args+=("$arg")
  done < <(compose_args)
  "${args[@]}" "$@"
}

apply_compose() {
  local args=()
  while IFS= read -r -d '' arg; do
    args+=("$arg")
  done < <(compose_args)
  run "${args[@]}" "$@"
}

compose_project_name() {
  run_compose config --format json 2>/dev/null | sed -n 's/^  "name": "\([^"]*\)",$/\1/p' | head -n 1
}

find_backup_root() {
  local extract_dir="$1"
  local candidate count

  candidate="$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d -name '????????T??????Z' | head -n 1)"
  count="$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d -name '????????T??????Z' | wc -l | tr -d ' ')"

  if [[ -z "$candidate" || "$count" != "1" ]]; then
    printf '[restore-full] error: archive must contain exactly one YYYYMMDDTHHMMSSZ backup directory\n' >&2
    exit 1
  fi

  printf '%s\n' "$candidate"
}

wait_for_postgres() {
  local i
  for i in $(seq 1 60); do
    if run_compose exec -T db sh -c 'pg_isready -U "${POSTGRES_USER:-growlee}" -d "${POSTGRES_DB:-growlee}" >/dev/null' >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  printf '[restore-full] error: PostgreSQL did not become ready in time\n' >&2
  exit 1
}

restore_volume_dir() {
  local source_dir="$1"
  local volume_short_name="$2"
  local label="$3"
  local project_name volume_name

  if [[ ! -d "$source_dir" ]]; then
    warn "$label not present in backup; skipped"
    return 0
  fi

  project_name="$(compose_project_name || true)"
  if [[ -z "$project_name" ]]; then
    printf '[restore-full] error: could not determine Docker Compose project name\n' >&2
    exit 1
  fi

  volume_name="${project_name}_${volume_short_name}"
  run docker volume create "$volume_name"
  run docker run --rm \
    -v "$volume_name:/target" \
    -v "$source_dir:/source:ro" \
    "$BACKUP_HELPER_IMAGE" \
    sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && cd /source && tar -cf - . | tar -xf - -C /target'
  log "Restored $label to Docker volume $volume_name"
}

verify_sha256_if_available() {
  local archive="$1"
  local sha_file="${archive}.sha256"

  if [[ -f "$sha_file" ]]; then
    log "Verifying SHA256 with $sha_file"
    (cd "$(dirname "$archive")" && sha256sum -c "$(basename "$sha_file")")
    return 0
  fi

  warn "SHA256 file not found next to archive; run manually if you keep it elsewhere"
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        printf '[restore-full] error: unknown argument: %s\n' "$1" >&2
        usage >&2
        exit 1
        ;;
    esac
  done

  if [[ -z "${BACKUP_ARCHIVE:-}" ]]; then
    printf '[restore-full] error: BACKUP_ARCHIVE is required\n' >&2
    usage >&2
    exit 1
  fi

  if [[ ! -f "$COMPOSE_FILE" ]]; then
    printf '[restore-full] error: run this script from the repository root; missing %s\n' "$COMPOSE_FILE" >&2
    exit 1
  fi

  if [[ ! -f "$BACKUP_ARCHIVE" ]]; then
    printf '[restore-full] error: backup archive not found: %s\n' "$BACKUP_ARCHIVE" >&2
    exit 1
  fi

  require_cmd docker
  require_cmd tar
  require_cmd sha256sum
  require_cmd find
  require_cmd sed

  verify_sha256_if_available "$BACKUP_ARCHIVE"

  local backup_dir
  EXTRACT_DIR="$RESTORE_WORKDIR/$(date -u +%Y%m%dT%H%M%SZ)-$$"
  rm -rf --one-file-system "$EXTRACT_DIR"
  mkdir -p "$EXTRACT_DIR"
  chmod 700 "$EXTRACT_DIR"
  trap 'rm -rf --one-file-system "$EXTRACT_DIR"' EXIT

  log "Extracting archive to $EXTRACT_DIR"
  tar -xzf "$BACKUP_ARCHIVE" -C "$EXTRACT_DIR"
  backup_dir="$(find_backup_root "$EXTRACT_DIR")"

  if [[ ! -f "$backup_dir/postgres.dump" ]]; then
    printf '[restore-full] error: postgres.dump not found in backup\n' >&2
    exit 1
  fi

  log "Backup directory: $backup_dir"
  if [[ -f "$backup_dir/metadata.txt" ]]; then
    log "metadata.txt found; inspect it manually if you need commit/image provenance"
  fi

  confirm_or_exit "This will restore Growlee from backup and may overwrite production state."

  log "Stopping Docker Compose stack without removing volumes"
  apply_compose down --remove-orphans

  if [[ -f "$backup_dir/.env.prod" ]]; then
    confirm_or_exit "About to overwrite $ENV_FILE from backup."
    run install -m 600 "$backup_dir/.env.prod" "$ENV_FILE"
    log "Restored $ENV_FILE"
  else
    warn ".env.prod not present in backup; keeping existing $ENV_FILE if any"
  fi

  if [[ -f "$backup_dir/Caddyfile" ]]; then
    mkdir -p deploy
    run install -m 644 "$backup_dir/Caddyfile" deploy/Caddyfile
    log "Restored deploy/Caddyfile"
  else
    warn "Caddyfile not present in backup; keeping existing deploy/Caddyfile if any"
  fi

  if [[ -d "$backup_dir/media_data" ]]; then
    confirm_or_exit "About to overwrite Docker volume media_data."
    restore_volume_dir "$backup_dir/media_data" media_data media_data
  else
    warn "media_data not present in backup; skipped"
  fi

  if [[ -d "$backup_dir/caddy_data" || -d "$backup_dir/caddy_config" ]]; then
    confirm_or_exit "About to overwrite Caddy Docker volumes from backup."
    restore_volume_dir "$backup_dir/caddy_data" caddy_data caddy_data
    restore_volume_dir "$backup_dir/caddy_config" caddy_config caddy_config
  else
    warn "caddy_data/caddy_config not present in backup; skipped"
  fi

  log "Starting PostgreSQL service"
  apply_compose up -d db
  if [[ "$DRY_RUN" == "1" ]]; then
    log "dry-run: would wait for PostgreSQL readiness"
  else
    wait_for_postgres
  fi

  confirm_or_exit "About to overwrite PostgreSQL using postgres.dump."
  if [[ "$DRY_RUN" == "1" ]]; then
    log "dry-run: would stream postgres.dump into pg_restore inside service db"
  else
    run_compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner --no-acl -U "${POSTGRES_USER:-growlee}" -d "${POSTGRES_DB:-growlee}"' < "$backup_dir/postgres.dump"
    log "Restored PostgreSQL dump"
  fi

  log "Starting full Docker Compose stack"
  apply_compose up -d

  log "Running migrations"
  apply_compose exec -T web python manage.py migrate --noinput

  log "Restore completed. Verify /healthz/ and admin login now."
}

main "$@"
