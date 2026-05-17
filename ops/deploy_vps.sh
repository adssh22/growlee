#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.prod}"
DEFAULT_APP_BASE_URL="https://growlee.fr"
HEALTHCHECK_TIMEOUT_SECONDS="${HEALTHCHECK_TIMEOUT_SECONDS:-120}"
HEALTHCHECK_INTERVAL_SECONDS="${HEALTHCHECK_INTERVAL_SECONDS:-5}"
SKIP_BACKUP=0
NO_PULL=0

log() {
  printf '[deploy-vps] %s\n' "$*"
}

warn() {
  printf '[deploy-vps] warning: %s\n' "$*" >&2
}

error() {
  printf '[deploy-vps] error: %s\n' "$*" >&2
}

usage() {
  cat <<'USAGE'
Usage:
  ./ops/deploy_vps.sh [--skip-backup] [--no-pull]

Options:
  --skip-backup  Explicitly skip the pre-deploy full backup.
  --no-pull      Redeploy the current local commit without git pull.
  -h, --help     Show this help.

Environment:
  COMPOSE_FILE                 Default: docker-compose.prod.yml
  ENV_FILE                     Default: .env.prod
  HEALTHCHECK_URL              Override healthcheck URL.
  HEALTHCHECK_TIMEOUT_SECONDS  Default: 120
  HEALTHCHECK_INTERVAL_SECONDS Default: 5

This script is intended for manual VPS deployments. It does not remove Docker
volumes and does not print .env.prod contents.
USAGE
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    error "missing required command: $1"
    exit 1
  fi
}

run_compose() {
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

read_env_value() {
  local key="$1"
  local value=""

  if [[ -f "$ENV_FILE" ]]; then
    value="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -n 1 | sed -E "s/^[[:space:]]*${key}=//" || true)"
    value="${value%$'\r'}"
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"
  fi

  printf '%s\n' "$value"
}

healthcheck_url() {
  local base_url

  if [[ -n "${HEALTHCHECK_URL:-}" ]]; then
    printf '%s\n' "$HEALTHCHECK_URL"
    return 0
  fi

  base_url="$(read_env_value APP_BASE_URL)"
  if [[ -z "$base_url" ]]; then
    base_url="$DEFAULT_APP_BASE_URL"
  fi

  base_url="${base_url%/}"
  printf '%s/healthz/\n' "$base_url"
}

show_recent_logs() {
  warn "recent web logs:"
  run_compose logs --tail=120 web || true
  warn "recent caddy logs:"
  run_compose logs --tail=120 caddy || true
}

run_healthcheck() {
  local url="$1"
  local elapsed=0

  log "Healthcheck: $url"
  while (( elapsed <= HEALTHCHECK_TIMEOUT_SECONDS )); do
    if curl -fsS --max-time 10 "$url" >/dev/null; then
      log "Healthcheck OK"
      return 0
    fi

    sleep "$HEALTHCHECK_INTERVAL_SECONDS"
    elapsed=$((elapsed + HEALTHCHECK_INTERVAL_SECONDS))
  done

  error "healthcheck failed after ${HEALTHCHECK_TIMEOUT_SECONDS}s: $url"
  show_recent_logs
  return 1
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --skip-backup)
        SKIP_BACKUP=1
        shift
        ;;
      --no-pull)
        NO_PULL=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        error "unknown argument: $1"
        usage >&2
        exit 1
        ;;
    esac
  done

  if [[ ! -f "$COMPOSE_FILE" || ! -f ops/backup_full_vps.sh ]]; then
    error "run this script from the repository root; missing $COMPOSE_FILE or ops/backup_full_vps.sh"
    exit 1
  fi

  require_cmd git
  require_cmd docker
  require_cmd curl

  if [[ ! -f "$ENV_FILE" ]]; then
    warn "$ENV_FILE not found; docker compose may fail or use defaults"
  fi

  local branch commit status health_url
  branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown')"
  commit="$(git rev-parse HEAD 2>/dev/null || printf 'unknown')"
  log "Git branch: $branch"
  log "Git commit: $commit"

  status="$(git status --short)"
  if [[ -n "$status" ]]; then
    warn "working tree is not clean; local changes may affect deployment:"
    printf '%s\n' "$status" >&2
  else
    log "Working tree clean"
  fi

  if [[ "$SKIP_BACKUP" == "1" ]]; then
    warn "backup skipped because --skip-backup was explicitly provided"
  else
    log "Running pre-deploy full backup"
    ./ops/backup_full_vps.sh
    log "Pre-deploy backup completed"
  fi

  if [[ "$NO_PULL" == "1" ]]; then
    warn "git pull skipped because --no-pull was provided"
  else
    log "Pulling latest code with --ff-only"
    git pull --ff-only
    commit="$(git rev-parse HEAD 2>/dev/null || printf 'unknown')"
    log "Git commit after pull: $commit"
  fi

  log "Validating Docker Compose config"
  run_compose config >/dev/null

  log "Deploying Docker Compose stack with build"
  if ! run_compose up -d --build; then
    error "docker compose up failed"
    run_compose ps || true
    show_recent_logs
    exit 1
  fi

  log "Docker Compose status"
  run_compose ps

  health_url="$(healthcheck_url)"
  run_healthcheck "$health_url"

  log "Deployment completed successfully"
}

main "$@"
