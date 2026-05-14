# Growlee — notes SaaS / cloud scale

## Stratégie base de données

Par défaut, Growlee doit scaler avec **une base PostgreSQL managée unique** et un modèle multi-tenant applicatif : chaque donnée métier est rattachée à un `merchant`.

C’est le meilleur compromis au démarrage :

- migrations simples ;
- analytics globaux plus faciles ;
- backups centralisés ;
- coût bas ;
- ajout de clients sans provisionner une base par client.

Éviter au début : **une base par client**. C’est plus lourd à maintenir : migrations N fois, backups N fois, routing complexe, support plus fragile.

## Connexion DB cloud

La configuration supporte maintenant :

```env
DATABASE_URL=postgresql://user:password@host:5432/growlee?sslmode=require
DB_CONN_MAX_AGE=60
DB_CONN_HEALTH_CHECKS=1
```

Fallback VPS/Docker compatible :

```env
POSTGRES_DB=growlee
POSTGRES_USER=growlee
POSTGRES_PASSWORD=...
POSTGRES_HOST=db
POSTGRES_PORT=5432
POSTGRES_SSLMODE=require
```

## Read replica optionnelle

Pour préparer le scale lecture :

```env
READ_REPLICA_DATABASE_URL=postgresql://user:password@replica-host:5432/growlee?sslmode=require
```

La replica est déclarée sous `DATABASES['replica']`. Elle n’est pas encore routée automatiquement : ajouter un database router seulement quand les lectures dashboard/analytics deviennent lourdes.

## Roadmap scale recommandée

1. VPS + PostgreSQL local ou managé.
2. PostgreSQL managé avec backups automatiques + PITR.
3. Redis pour cache / sessions / rate limiting.
4. Stockage objet S3 compatible pour médias marchands.
5. Workers séparés pour SMS/email/wallet/automations.
6. Read replica pour analytics si besoin.
7. Partitionnement ou sharding seulement beaucoup plus tard.

## Règle multi-tenant

Chaque requête admin doit filtrer par `merchant` issu de `MerchantMembership`.
Avant scale sérieux, ajouter des tests automatiques qui prouvent qu’un marchand A ne peut pas lire/modifier :

- campagnes ;
- clients ;
- récompenses ;
- sessions de jeu ;
- wallet passes ;
- assets ;
- exports ;
- automations ;

d’un marchand B.

## Sécurité et exploitation ajoutées

### Rate limiting

Les vues sensibles sont maintenant limitées par cache Django :

- `/login/`
- `/signup/`
- `/contact/`
- `/api/contact/`
- `/play/<slug>/` sur POST
- `/gain/<token>/` sur POST

Variables utiles :

```env
RATELIMIT_ENABLED=1
RATELIMIT_LOGIN_ATTEMPTS=8
RATELIMIT_SIGNUP_ATTEMPTS=5
RATELIMIT_PLAY_POST_ATTEMPTS=30
RATELIMIT_CONTACT_ATTEMPTS=10
RATELIMIT_GAIN_ATTEMPTS=20
```

En multi-worker ou multi-node, utiliser Redis pour un compteur partagé :

```env
REDIS_URL=redis://redis:6379/1
```

### Uploads

Les images marchand sont validées côté serveur :

- vrai format image vérifié avec Pillow ;
- PNG/JPG/WebP uniquement ;
- taille maximale ;
- dimensions maximales ;
- payload non-image rejeté même si l’extension est `.png`.

### Tests isolation SaaS

Des tests couvrent les premiers cas critiques : un marchand ne peut pas modifier la campagne d’un autre marchand via le toggle admin.
À étendre systématiquement à chaque nouvelle vue admin.

### Ops inclus

Scripts ajoutés :

- `ops/backup_postgres.sh` : backup quotidien PostgreSQL au format custom ;
- `ops/restore_check_postgres.sh` : test de restauration sur base jetable ;
- `ops/monitoring_check.sh` : disque, RAM, load, taille DB, expiration SSL ;
- `ops/INFRA-HARDENING.md` : firewall, SSH, fail2ban, updates, reverse proxy HTTPS.
