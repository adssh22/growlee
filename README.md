# Growlee

Growlee est une plateforme SaaS multi-tenant de croissance client pour commerces physiques.

## Stack MVP

- Backend + rendu web: Django 5
- Base de données: PostgreSQL
- Conteneurisation: Docker Compose

## Ce socle contient

- multi-tenant simple par `Merchant`
- espace commerçant avec login Django
- dashboard commerçant MVP
- mode employé cloisonné avec scan QR/carte et validation de gains
- sortie du mode employé par ré-authentification propriétaire/manager
- page de configuration commerce / campagne / reward / point d'entrée
- flow client public `/play/<slug>/` réaligné sur un parcours en étapes
- landing brandée avec exemple QR façade
- étape jeu MVP
- collecte contact avec consentement RGPD
- email de gain avec lien unique temporaire
- page gain activable pendant 15 minutes avec code + QR de validation
- page avis optionnelle
- étape wallet placeholder Apple Wallet / Google Wallet
- création de `Customer` et `GameSession` depuis le flow public
- preview QR SVG par point d'entrée
- admin Django natif via `/django-admin/`
- modèles initiaux Merchant, Campaign, EntryPoint, Reward, Customer, GameSession, MerchantMembership

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
- Admin Django: http://localhost:8000/django-admin/

## Compte de démo

- login: `demo`
- password: `demo1234`

## Étapes suivantes recommandées

1. brancher un provider SMS réel
2. configurer HTTPS en prod pour le scan caméra live
3. finaliser certificats Apple Wallet et issuer Google Wallet
4. ajouter écrans CRUD dédiés pour campagnes et entry points multiples
5. ajouter statuts d'expiration / reporting avancé des gains
