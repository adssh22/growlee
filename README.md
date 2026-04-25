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
- page de configuration commerce / campagne / reward / point d'entrée
- flow client public `/play/<slug>/` réaligné sur un parcours en étapes
- landing brandée
- étape jeu MVP
- collecte contact avec consentement RGPD
- page gain avec code de claim
- page avis optionnelle
- étape wallet placeholder
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

1. appliquer les migrations dans Docker au prochain lancement
2. remplacer le faux QR SVG par une vraie génération QR
3. ajouter écrans CRUD dédiés pour campagnes et entry points multiples
4. ajouter statuts d'expiration / validité des gains
5. ajouter SMS et relances
