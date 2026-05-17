# Growlee — backups VPS Docker Compose

Ce runbook couvre le backup complet exploitable du VPS Growlee en production Docker Compose.

## Script recommandé

```bash
chmod +x ops/backup_full_vps.sh
FULL_BACKUP_RETENTION_DAYS=30 ./ops/backup_full_vps.sh
```

Le script doit être lancé depuis la racine du repo, là où se trouve `docker-compose.prod.yml`.

Par défaut, il écrit dans `/var/backups` : il faut donc l’exécuter avec un utilisateur qui a les permissions nécessaires, ou lancer via `sudo`, ou définir `FULL_BACKUP_ROOT` vers un chemin accessible.

Par défaut, il écrit dans :

```text
/var/backups/growlee/full/
```

Chaque exécution crée d’abord un dossier de travail horodaté :

```text
/var/backups/growlee/full/YYYYMMDDTHHMMSSZ/
```

Puis produit l’archive finale :

```text
/var/backups/growlee/full/growlee-full-YYYYMMDDTHHMMSSZ.tar.gz
/var/backups/growlee/full/growlee-full-YYYYMMDDTHHMMSSZ.tar.gz.sha256
```

Le dossier temporaire est supprimé après création réussie de l’archive.

## Contenu sauvegardé

- PostgreSQL : dump custom `pg_dump --format=custom --no-owner --no-acl` depuis le service Compose `db`.
- `.env.prod` si présent, copié dans l’archive sans afficher son contenu.
- `deploy/Caddyfile`.
- `media_data` depuis `/app/media` du service `web`, si le conteneur est disponible.
- `caddy_data` depuis `/data` du service `caddy`, si disponible.
- `caddy_config` depuis `/config` du service `caddy`, si disponible.
- `metadata.txt` avec : date UTC, commit Git, branche Git, `docker compose ps`, images Compose.

Le script n’affiche pas les secrets dans les logs. Attention : `.env.prod` est volontairement inclus dans l’archive ; l’archive doit donc être stockée et transférée comme un secret.

## Stockage média local ou S3

Si `DJANGO_MEDIA_STORAGE=s3`, le volume Docker `media_data` peut être vide ou non critique. Dans ce cas, la restauration complète dépend aussi du bucket S3 et de sa propre politique de backup/versioning côté fournisseur.

Si les médias sont stockés localement, `media_data` fait partie du backup applicatif important.

## Variables configurables

```bash
FULL_BACKUP_ROOT=/var/backups/growlee/full
FULL_BACKUP_RETENTION_DAYS=30
COMPOSE_FILE=docker-compose.prod.yml
ENV_FILE=.env.prod
BACKUP_HELPER_IMAGE=alpine:3.20
```

`FULL_BACKUP_RETENTION_DAYS` doit être un entier positif ou nul. Par défaut : `30`.

`BACKUP_HELPER_IMAGE` sert seulement au fallback de copie directe d’un volume Docker quand le conteneur applicatif n’est pas disponible.

## Échec attendu si PostgreSQL est inaccessible

Le script vérifie `pg_isready` dans le service Compose `db` avant de lancer le dump.

Si PostgreSQL n’est pas accessible, il échoue avant de produire une archive incomplète :

```text
[backup-full] error: PostgreSQL is not accessible via docker compose service db
```

## Vérification d’intégrité

Sur le VPS :

```bash
cd /var/backups/growlee/full
sha256sum -c growlee-full-YYYYMMDDTHHMMSSZ.tar.gz.sha256
```

Lister le contenu sans extraction :

```bash
tar -tzf growlee-full-YYYYMMDDTHHMMSSZ.tar.gz
```

## Test de restauration PostgreSQL

Utiliser une base jetable, jamais la production :

```bash
RESTORE_DATABASE_URL='postgresql://user:password@host:5432/growlee_restore_check' \
BACKUP_FILE='/path/to/postgres.dump' \
./ops/restore_check_postgres.sh
```

Pour récupérer `postgres.dump` depuis une archive complète :

```bash
mkdir -p /tmp/growlee-restore-check
tar -xzf /var/backups/growlee/full/growlee-full-YYYYMMDDTHHMMSSZ.tar.gz -C /tmp/growlee-restore-check
find /tmp/growlee-restore-check -name postgres.dump -print
```

## Exemple cron

```cron
17 2 * * * cd /srv/growlee && FULL_BACKUP_RETENTION_DAYS=30 ./ops/backup_full_vps.sh >> /var/log/growlee-backup-full.log 2>&1
```

Le log ne doit pas contenir le contenu de `.env.prod`, mais l’archive et son `.sha256` doivent rester protégés (`chmod 600`).

## Notes restauration complète

Ordre conseillé :

1. Restaurer le repo au commit indiqué dans `metadata.txt`.
2. Restaurer `.env.prod` depuis l’archive, en permissions strictes.
3. Restaurer `deploy/Caddyfile` si nécessaire.
4. Restaurer les volumes `media_data`, `caddy_data`, `caddy_config` selon le besoin.
5. Restaurer PostgreSQL avec `pg_restore` sur une base propre.
6. Redémarrer les services Docker Compose et vérifier `/healthz/`.

Ne jamais supprimer les volumes Docker de production sans snapshot/backup vérifié.
