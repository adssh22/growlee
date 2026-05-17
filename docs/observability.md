# Growlee — observabilité applicative

Growlee écrit ses logs applicatifs sur stdout/stderr via Docker. Sentry est optionnel et sert à centraliser les erreurs applicatives critiques, notamment les 500 Django et les exceptions non gérées.

## Configuration Sentry

Sentry est désactivé par défaut. Il ne s’initialise que si `SENTRY_DSN` est défini.

Dans `.env.prod` :

```env
SENTRY_DSN=https://PUBLIC_KEY@oXXXX.ingest.sentry.io/PROJECT_ID
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.0
SENTRY_SEND_DEFAULT_PII=0
```

Valeurs recommandées :

- `SENTRY_DSN` : DSN du projet Sentry. Laisser vide pour désactiver.
- `SENTRY_ENVIRONMENT=production` sur le VPS prod.
- `SENTRY_TRACES_SAMPLE_RATE=0.0` pour ne pas collecter de traces performance tant que ce n’est pas nécessaire.
- `SENTRY_SEND_DEFAULT_PII=0` pour éviter l’envoi automatique de données personnelles.

Après modification :

```bash
./ops/deploy_vps.sh --no-pull
```

Sentry ne doit jamais être requis en CI ou en local : si `SENTRY_DSN` est vide, l’application démarre sans Sentry.

## Ce qu’il faut surveiller

Priorité haute :

- erreurs HTTP 500 Django ;
- erreurs Stripe webhook ;
- webhooks Stripe ignorés ou invalides ;
- merchant introuvable lors d’un événement Stripe ;
- `NotificationJob` en échec ;
- erreurs répétées des workers ;
- `/healthz/` non OK ;
- erreurs Caddy TLS / reverse proxy ;
- erreurs de configuration média S3 si `DJANGO_MEDIA_STORAGE=s3`.

Priorité moyenne :

- refus QR redirect pour URL invalide ;
- refus `claim_reward` par cooldown, surtout si volume anormal ;
- lenteur ou backlog de notifications ;
- jobs metrics trop longs ou en erreur.

## Données sensibles

Les logs applicatifs ne doivent pas contenir :

- secrets ;
- tokens ;
- contenu de `.env.prod` ;
- numéro de téléphone complet ;
- email complet ;
- payloads complets Stripe ou webhook.

Les logs ajoutés utilisent des identifiants internes, types d’événement, hashes courts ou suffixes d’identifiants externes quand nécessaire.

## Lire les logs Docker

Depuis la racine du repo sur le VPS :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
```

Logs web :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail=200 web
```

Suivi temps réel web :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f web
```

Logs Caddy :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail=200 caddy
```

Logs worker notifications :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail=200 notification-worker
```

Logs worker metrics :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail=200 metrics-worker
```

Tous les services utiles :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail=200 web caddy notification-worker metrics-worker
```

## Commandes utiles

Healthcheck public :

```bash
curl -fsS https://growlee.fr/healthz/
```

Healthcheck local via Caddy ou web :

```bash
curl -fsS http://127.0.0.1/healthz/ || curl -fsS http://127.0.0.1:8000/healthz/
```

État Compose :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
```

Redéployer sans pull après changement `.env.prod` :

```bash
./ops/deploy_vps.sh --no-pull
```

Forcer un passage du worker notifications :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T web \
  python manage.py process_notification_jobs --limit 100 --include-failed
```

Filtrer les échecs notification dans les logs récents :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail=500 notification-worker web | grep 'NotificationJob failed'
```

Filtrer Stripe :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail=500 web | grep 'Stripe webhook'
```

## Logs applicatifs ajoutés

Growlee logge explicitement, sans payload sensible :

- `Stripe webhook received` ;
- `Stripe webhook ignored` ;
- `Stripe webhook error` ;
- `Stripe webhook merchant not found` ;
- `NotificationJob failed` ;
- `process_notification_jobs summary` ;
- `QR redirect refused` ;
- `claim_reward refused by cooldown` ;
- `S3 media storage configuration error`.

## Réaction recommandée

1. Vérifier `/healthz/`.
2. Lire `docker compose ps`.
3. Lire logs `web` + `caddy`.
4. Pour Stripe : vérifier le dashboard Stripe puis logs `Stripe webhook`.
5. Pour notifications : vérifier `NotificationJob failed`, provider, channel et volume de jobs.
6. Pour S3 : vérifier uniquement la présence/configuration des variables, sans afficher les secrets.
7. Si déploiement récent : consulter `docs/deploy.md` et rollback si nécessaire.
