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
