# Growlee — restauration complète VPS Docker Compose

Cette procédure restaure Growlee depuis une archive générée par `ops/backup_full_vps.sh`.

Elle couvre un VPS neuf ou un incident sur un VPS existant.

## Ce que contient un backup complet

Une archive complète doit contenir au minimum :

- `postgres.dump` : dump PostgreSQL custom format.
- `media_data/` : médias locaux si utilisés.
- `.env.prod` : secrets et configuration production.
- `Caddyfile` : copie de `deploy/Caddyfile`.
- `caddy_data/` et `caddy_config/` si disponibles.
- `metadata.txt` : date UTC, commit Git, branche Git, état Compose/images au moment du backup.

Si `DJANGO_MEDIA_STORAGE=s3`, `media_data/` peut être vide ou non critique. Dans ce cas, vérifier aussi la restauration/versioning du bucket S3.

## Principes de sécurité

- Ne jamais restaurer automatiquement sur production sans confirmation humaine.
- Ne jamais afficher le contenu de `.env.prod` dans les logs.
- Ne jamais utiliser `docker compose down -v` pour cette procédure : cela supprime les volumes.
- Toujours vérifier le SHA256 avant extraction/restauration.
- Garder l’archive `.tar.gz` protégée : elle contient potentiellement `.env.prod`.

## Option A — restauration assistée par script

Le script `ops/restore_full_vps.sh` automatise les étapes mécaniques, mais demande des confirmations fortes avant les écrasements.

### Dry-run

Depuis la racine du repo :

```bash
chmod +x ops/restore_full_vps.sh
BACKUP_ARCHIVE=/var/backups/growlee/full/growlee-full-YYYYMMDDTHHMMSSZ.tar.gz \
./ops/restore_full_vps.sh --dry-run
```

Le mode `--dry-run` vérifie l’archive, extrait dans un dossier temporaire, puis affiche les commandes destructrices au lieu de les exécuter.

### Restauration réelle

```bash
BACKUP_ARCHIVE=/var/backups/growlee/full/growlee-full-YYYYMMDDTHHMMSSZ.tar.gz \
./ops/restore_full_vps.sh
```

Le script refuse de démarrer sans `BACKUP_ARCHIVE`.

Il demande de taper exactement :

```text
RESTORE GROWLEE FROM BACKUP
```

avant :

- restauration globale sur l’environnement courant ;
- écrasement de `.env.prod` ;
- écrasement du volume `media_data` ;
- écrasement des volumes `caddy_data` / `caddy_config` ;
- restauration PostgreSQL.

Variables disponibles :

```bash
COMPOSE_FILE=docker-compose.prod.yml
ENV_FILE=.env.prod
RESTORE_WORKDIR=/tmp/growlee-restore
BACKUP_HELPER_IMAGE=alpine:3.20
```

Le script utilise Docker Compose v2 (`docker compose`).

## Option B — procédure manuelle

Les commandes ci-dessous sont copiables. Adapter `YYYYMMDDTHHMMSSZ`.

### 1. Préparer les chemins

```bash
cd /srv/growlee
export BACKUP_ARCHIVE=/var/backups/growlee/full/growlee-full-YYYYMMDDTHHMMSSZ.tar.gz
export RESTORE_DIR=/tmp/growlee-restore-YYYYMMDDTHHMMSSZ
```

### 2. Vérifier l’intégrité SHA256

Si le fichier `.sha256` est à côté de l’archive :

```bash
cd "$(dirname "$BACKUP_ARCHIVE")"
sha256sum -c "$(basename "$BACKUP_ARCHIVE").sha256"
cd /srv/growlee
```

Résultat attendu :

```text
growlee-full-YYYYMMDDTHHMMSSZ.tar.gz: OK
```

### 3. Extraire l’archive

```bash
rm -rf --one-file-system "$RESTORE_DIR"
mkdir -p "$RESTORE_DIR"
chmod 700 "$RESTORE_DIR"
tar -xzf "$BACKUP_ARCHIVE" -C "$RESTORE_DIR"
find "$RESTORE_DIR" -maxdepth 2 -type f -o -type d
```

Identifier le dossier extrait :

```bash
export BACKUP_DIR="$RESTORE_DIR/YYYYMMDDTHHMMSSZ"
ls -la "$BACKUP_DIR"
```

Inspecter la provenance sans afficher les secrets :

```bash
sed -n '1,120p' "$BACKUP_DIR/metadata.txt"
```

### 4. Arrêter Docker Compose sans supprimer les volumes

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml down --remove-orphans
```

Sur VPS neuf sans `.env.prod` existant, utiliser temporairement :

```bash
docker compose -f docker-compose.prod.yml down --remove-orphans
```

Ne pas ajouter `-v`.

### 5. Restaurer `.env.prod`

```bash
install -m 600 "$BACKUP_DIR/.env.prod" .env.prod
```

Ne pas faire `cat .env.prod` dans un terminal partagé ou un log.

### 6. Restaurer `deploy/Caddyfile`

```bash
mkdir -p deploy
install -m 644 "$BACKUP_DIR/Caddyfile" deploy/Caddyfile
```

### 7. Restaurer `media_data`

Créer/écraser le contenu du volume Compose `media_data` sans supprimer le volume lui-même :

```bash
PROJECT_NAME=$(docker compose --env-file .env.prod -f docker-compose.prod.yml config --format json | sed -n 's/^  "name": "\([^"]*\)",$/\1/p' | head -n 1)
docker volume create "${PROJECT_NAME}_media_data" >/dev/null
docker run --rm \
  -v "${PROJECT_NAME}_media_data:/target" \
  -v "$BACKUP_DIR/media_data:/source:ro" \
  alpine:3.20 \
  sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && cd /source && tar -cf - . | tar -xf - -C /target'
```

Si `media_data/` n’existe pas dans le backup et que les médias sont sur S3, vérifier le bucket S3 au lieu de bloquer la restauration.

### 8. Restaurer `caddy_data` et `caddy_config` si présents

```bash
PROJECT_NAME=$(docker compose --env-file .env.prod -f docker-compose.prod.yml config --format json | sed -n 's/^  "name": "\([^"]*\)",$/\1/p' | head -n 1)

if [ -d "$BACKUP_DIR/caddy_data" ]; then
  docker volume create "${PROJECT_NAME}_caddy_data" >/dev/null
  docker run --rm \
    -v "${PROJECT_NAME}_caddy_data:/target" \
    -v "$BACKUP_DIR/caddy_data:/source:ro" \
    alpine:3.20 \
    sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && cd /source && tar -cf - . | tar -xf - -C /target'
fi

if [ -d "$BACKUP_DIR/caddy_config" ]; then
  docker volume create "${PROJECT_NAME}_caddy_config" >/dev/null
  docker run --rm \
    -v "${PROJECT_NAME}_caddy_config:/target" \
    -v "$BACKUP_DIR/caddy_config:/source:ro" \
    alpine:3.20 \
    sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && cd /source && tar -cf - . | tar -xf - -C /target'
fi
```

Restaurer `caddy_data` conserve notamment les certificats ACME. Si ce volume n’est pas restauré, Caddy peut régénérer les certificats au redémarrage si DNS/ports 80/443 sont corrects.

### 9. Restaurer PostgreSQL

Démarrer uniquement PostgreSQL :

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d db
```

Attendre que la base réponde :

```bash
until docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_isready -U "${POSTGRES_USER:-growlee}" -d "${POSTGRES_DB:-growlee}" >/dev/null'; do
  sleep 2
done
```

Restaurer le dump :

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_restore --clean --if-exists --no-owner --no-acl -U "${POSTGRES_USER:-growlee}" -d "${POSTGRES_DB:-growlee}"' \
  < "$BACKUP_DIR/postgres.dump"
```

Cette étape écrase les objets présents dans la base cible. Ne jamais la lancer contre une production active sans validation explicite.

### 10. Relancer Docker Compose

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

### 11. Lancer les migrations si nécessaire

Si le repo restauré est au même commit que `metadata.txt`, les migrations devraient déjà correspondre. Après incident ou déploiement sur commit plus récent, lancer :

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T web \
  python manage.py migrate --noinput
```

### 12. Vérifier l’état applicatif

État Compose :

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
```

Healthcheck HTTP local :

```bash
curl -fsS http://127.0.0.1/healthz/ || curl -fsS http://127.0.0.1:8000/healthz/
```

Selon la topologie réseau du VPS, vérifier aussi :

```bash
curl -fsS https://growlee.fr/healthz/
```

Logs utiles :

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=100 web
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=100 caddy
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=100 notification-worker
docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail=100 metrics-worker
```

### 13. Vérifier le login admin

Depuis un navigateur :

```text
https://growlee.fr/growlee-control/
```

Vérifier :

- chargement de la page ;
- login superuser/staff ;
- MFA si activé ;
- accès à au moins une page merchant ;
- présence des médias si stockage local ;
- absence d’erreurs 500 dans les logs `web`.

## Test de restauration sur base jetable / staging

Objectif : valider qu’un backup est exploitable sans toucher à la production.

### Test minimal PostgreSQL sur base jetable

Extraire seulement le dump :

```bash
export BACKUP_ARCHIVE=/var/backups/growlee/full/growlee-full-YYYYMMDDTHHMMSSZ.tar.gz
export RESTORE_DIR=/tmp/growlee-restore-check
rm -rf --one-file-system "$RESTORE_DIR"
mkdir -p "$RESTORE_DIR"
tar -xzf "$BACKUP_ARCHIVE" -C "$RESTORE_DIR"
export BACKUP_FILE=$(find "$RESTORE_DIR" -name postgres.dump -print -quit)
```

Créer une base jetable hors production, puis :

```bash
RESTORE_DATABASE_URL='postgresql://user:password@host:5432/growlee_restore_check' \
BACKUP_FILE="$BACKUP_FILE" \
./ops/restore_check_postgres.sh
```

Supprimer la base jetable après vérification.

### Test staging complet

Sur un VPS staging ou une machine isolée :

```bash
git clone git@github.com:adssh22/growlee.git /srv/growlee-staging
cd /srv/growlee-staging
BACKUP_ARCHIVE=/path/to/growlee-full-YYYYMMDDTHHMMSSZ.tar.gz ./ops/restore_full_vps.sh --dry-run
BACKUP_ARCHIVE=/path/to/growlee-full-YYYYMMDDTHHMMSSZ.tar.gz ./ops/restore_full_vps.sh
```

Avant le test réel, remplacer les domaines/secrets sortants dans `.env.prod` restauré si nécessaire pour éviter emails/SMS réels depuis staging.

Vérifier ensuite :

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:8000/healthz/
```

Puis tester le login admin sur l’URL staging.
