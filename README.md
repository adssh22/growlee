# Growlee

Growlee est une plateforme SaaS multi-tenant de croissance client pour commerces physiques.

## Stack MVP

- Backend + rendu web: Django 5
- Base de données: PostgreSQL
- Conteneurisation: Docker Compose

## Fonctionnalités couvertes

- multi-tenant simple par `Merchant`
- espace commerçant avec login Django
- dashboard commerçant MVP avec nombre de gains gagnés
- mode employé cloisonné avec scan QR/carte, photo QR fallback et validation de gains
- sortie du mode employé par PIN employeur ou ré-authentification propriétaire/manager
- page de configuration commerce / campagne / reward / point d'entrée
- accès démo apporteur d'affaires via Growlee Control
- flow client public `/play/<slug>/` mobile-first
- landing brandée
- étape jeu MVP
- collecte contact avec consentement RGPD
- email HTML de gain avec lien unique temporaire
- SMS transactionnel configurable: console, Twilio ou Brevo
- page gain activable pendant 15 minutes avec code + QR de validation employé
- page avis optionnelle
- étape wallet Apple Wallet / Google Wallet avec badges et statut de configuration
- création de `Customer`, `GameSession` et `WalletPass` depuis le flow public
- preview QR SVG par point d'entrée
- admin Django natif via `/django-admin/`

## Lancement

```bash
docker compose up --build
```

## URLs

- App: http://localhost:8000
- Login commerçant: http://localhost:8000/login/
- Dashboard home: http://localhost:8000/admin/
- Mode employé: http://localhost:8000/admin/employee/
- Onboarding: http://localhost:8000/admin/onboarding/
- Configuration mini jeu: http://localhost:8000/admin/game/
- Scan / Tap / point d'entrée: http://localhost:8000/admin/setup/
- CRM clients: http://localhost:8000/admin/customers/
- Rewards: http://localhost:8000/admin/rewards/
- Analytics: http://localhost:8000/admin/analytics/
- Relances automatiques: http://localhost:8000/admin/automations/
- Flow client demo: http://localhost:8000/play/demo-bistro/
- Growlee Control: http://localhost:8000/growlee-control/merchants/
- Admin Django: http://localhost:8000/django-admin/
- Healthcheck: http://localhost:8000/healthz/

## Compte de démo

La commande `python manage.py seed_demo` crée les comptes de démonstration en développement:

- superuser: `demo` / `demo1234`
- commerçant: `demo-merchant` / `demo1234`

Sécurité: la commande refuse de s’exécuter quand `DJANGO_DEBUG=0`, sauf si `ALLOW_DEMO_SEED=1` est explicitement défini.

## Configuration production

Copier `.env.prod.example` vers `.env.prod` sur le VPS, puis renseigner les variables utiles. `docker-compose.prod.yml` accepte l’absence locale de `.env.prod` pour permettre `docker compose -f docker-compose.prod.yml config`, mais le déploiement réel nécessite notamment `POSTGRES_PASSWORD` et `DJANGO_SECRET_KEY`.

### Observabilité / healthcheck

Growlee expose un endpoint JSON minimal sur `/healthz/`.

- réponse nominale: `200 {"status":"ok"}`
- si la base de données ne répond pas: `503 {"status":"unhealthy"}`

L’endpoint ne retourne aucun détail interne. En production, `docker-compose.prod.yml` utilise ce endpoint comme `healthcheck` du service `web`.

### Cache Redis / rate-limit

En production, `docker-compose.prod.yml` lance un service Redis interne non exposé publiquement et transmet `REDIS_URL=redis://redis:6379/1` au service web. Django utilise alors `django-redis` comme cache partagé, ce qui rend le rate-limit global entre workers Gunicorn.

Sans `REDIS_URL`, Django retombe sur `LocMemCache`, acceptable en développement mais non partagé entre workers.

### Email

En dev, les emails sortent en console. En prod, configurer un backend SMTP Django:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DEFAULT_FROM_EMAIL=Growlee <hello@votre-domaine.fr>
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
EMAIL_USE_TLS=1
```

### Notifications email/SMS asynchrones

En production, `docker-compose.prod.yml` lance un service `notification-worker` sans port exposé. Il utilise la même image que `web` et traite les `NotificationJob` en boucle:

```bash
python manage.py process_notification_jobs --limit 100 --include-failed
```

Intervalle configurable dans `.env.prod`:

```env
NOTIFICATION_WORKER_INTERVAL_SECONDS=60
```

Vérifier le worker et les jobs:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f notification-worker
docker compose --env-file .env.prod -f docker-compose.prod.yml exec web python manage.py process_notification_jobs --limit 20 --include-failed
```

Les jobs échoués restent en `failed` avec `last_error` et sont relançables par la commande ci-dessus ou via l’admin Django.

### SMS

Providers supportés:

```env
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+33...
```

ou:

```env
SMS_PROVIDER=brevo
BREVO_API_KEY=...
BREVO_SMS_SENDER=Growlee
```

### Apple Wallet / Google Wallet

Les boutons et la préparation technique sont intégrés. Les licences/comptes restent à créer côté Apple/Google:

- Apple Developer Program actif
- Pass Type ID
- Team ID
- certificat PassKit + clé privée + WWDR
- Google Wallet API activée
- Issuer ID Google Wallet
- service account JSON

Variables:

```env
APPLE_WALLET_PASS_TYPE_ID=
APPLE_WALLET_TEAM_ID=
APPLE_WALLET_CERT_PATH=
APPLE_WALLET_KEY_PATH=
APPLE_WALLET_WWDR_CERT_PATH=
GOOGLE_WALLET_ISSUER_ID=
GOOGLE_WALLET_SERVICE_ACCOUNT_PATH=
```

## Notes importantes

- Le scan caméra live nécessite HTTPS en prod. En HTTP local/réseau, certains navigateurs bloquent la caméra; Growlee propose alors la photo QR ou la saisie manuelle.
- Les vrais `.pkpass` Apple et save URLs Google sont préparés côté modèle/service, mais nécessitent les certificats et comptes officiels ci-dessus.
