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

## Compte de démo

- login: `demo`
- password: `demo1234`

## Configuration production

Copier `.env.example`, puis renseigner les variables utiles.

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
