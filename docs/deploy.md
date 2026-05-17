# Growlee — déploiement manuel VPS

Le déploiement production Growlee sur VPS doit passer par `ops/deploy_vps.sh`.

Le script sécurise la procédure classique :

1. affiche branche et commit Git courants ;
2. signale si le working tree n’est pas propre ;
3. lance un backup complet avant mise à jour ;
4. arrête le déploiement si le backup échoue ;
5. fait `git pull --ff-only` ;
6. valide `docker compose config` ;
7. lance `docker compose up -d --build` ;
8. affiche `docker compose ps` ;
9. vérifie `/healthz/` ;
10. affiche les logs récents `web` et `caddy` si le healthcheck échoue.

Le script ne supprime pas les volumes Docker et ne doit pas afficher le contenu de `.env.prod`.

## Commande standard

Depuis la racine du repo sur le VPS :

```bash
chmod +x ops/deploy_vps.sh
./ops/deploy_vps.sh
```

## Options

### Ignorer explicitement le backup

À utiliser seulement si un backup récent et vérifié existe déjà :

```bash
./ops/deploy_vps.sh --skip-backup
```

L’option est volontairement explicite : sans elle, le backup complet `ops/backup_full_vps.sh` est obligatoire.

### Redéployer le commit local sans pull

Utile pour relancer un build ou appliquer une modification déjà présente localement :

```bash
./ops/deploy_vps.sh --no-pull
```

### Validation locale minimale

Pour tester le script sans backup ni pull :

```bash
./ops/deploy_vps.sh --skip-backup --no-pull
```

Cette commande lance quand même `docker compose up -d --build` et le healthcheck. Elle est prévue pour le VPS ou un staging capable de servir l’application.

## Variables configurables

```bash
COMPOSE_FILE=docker-compose.prod.yml
ENV_FILE=.env.prod
HEALTHCHECK_URL=https://growlee.fr/healthz/
HEALTHCHECK_TIMEOUT_SECONDS=120
HEALTHCHECK_INTERVAL_SECONDS=5
```

Si `HEALTHCHECK_URL` n’est pas défini, le script utilise `APP_BASE_URL` dans `.env.prod`, puis ajoute `/healthz/`.

Si `APP_BASE_URL` n’est pas présent, il utilise :

```text
https://growlee.fr/healthz/
```

## En cas d’échec

### Backup échoué

Le déploiement s’arrête immédiatement. Corriger la cause avant de relancer : PostgreSQL inaccessible, permissions `/var/backups`, disque plein, Docker indisponible, etc.

### `git pull --ff-only` échoué

Le dépôt local a probablement divergé ou contient des changements incompatibles. Ne pas forcer en production sans comprendre. Inspecter :

```bash
git status
git log --oneline --decorate --graph --max-count=20
```

### Compose config échoué

Vérifier :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod config
```

Ne pas lancer `up` tant que la config n’est pas valide.

### `docker compose up` ou healthcheck échoué

Le script affiche automatiquement l’état Compose et les logs récents :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail=120 web
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail=120 caddy
```

Si l’erreur concerne les ports `80` ou `443`, vérifier qu’aucun autre reverse proxy système n’écoute déjà :

```bash
sudo ss -ltnp '( sport = :80 or sport = :443 )'
```

Vérifier aussi :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
curl -fsS https://growlee.fr/healthz/
```

## Rollback rapide

Si un déploiement casse après un backup OK :

1. identifier le dernier commit sain ;
2. revenir dessus proprement ;
3. relancer le déploiement sans pull si nécessaire.

Exemple :

```bash
git checkout <commit_sain>
./ops/deploy_vps.sh --skip-backup --no-pull
```

Pour une restauration complète données + volumes, utiliser `docs/restore.md` et `ops/restore_full_vps.sh`.
