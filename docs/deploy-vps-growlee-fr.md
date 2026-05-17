# Déploiement VPS — growlee.fr

Objectif : exposer Growlee publiquement en HTTPS sur `growlee.fr` avec Docker Compose, Django en production, PostgreSQL et Caddy pour Let's Encrypt.

## 1. DNS

Créer les enregistrements DNS :

- `A growlee.fr -> IP_DU_VPS`
- `A www.growlee.fr -> IP_DU_VPS`

Attendre la propagation avant de lancer Caddy.

## 2. Préparer le VPS

Installer Docker + plugin Compose, puis ouvrir le firewall :

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

## 3. Déployer le code

```bash
git clone <URL_DU_REPO> growlee
cd growlee
cp .env.prod.example .env.prod
```

Éditer `.env.prod` :

- `POSTGRES_PASSWORD` long et unique
- `DJANGO_SECRET_KEY` généré proprement
- `LETSENCRYPT_EMAIL`
- SMTP/SMS/paiement si prêts

Générer une clé Django :

```bash
docker run --rm python:3.12-slim python - <<'PY'
import secrets
print(secrets.token_urlsafe(50))
PY
```

## 4. Lancer en production

Utiliser le script de déploiement sécurisé :

```bash
chmod +x ops/deploy_vps.sh
./ops/deploy_vps.sh
```

Il lance un backup complet avant mise à jour, valide Docker Compose, déploie avec build, puis vérifie `/healthz/`. Voir `docs/deploy.md` pour les options `--skip-backup` et `--no-pull`.

La stack fait automatiquement :

- migration DB
- `collectstatic`
- lancement Gunicorn
- HTTPS Let's Encrypt via Caddy
- redirection `www.growlee.fr` vers `growlee.fr`

## 5. Créer un superadmin

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py createsuperuser
```

## 6. Vérifications

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f caddy web
curl -I https://growlee.fr
curl -I https://www.growlee.fr
```

Attendu :

- `https://growlee.fr` répond en 200/302 selon page
- certificat HTTPS valide
- `www.growlee.fr` redirige vers `growlee.fr`

## 7. Mises à jour

Toujours passer par le script sécurisé :

```bash
./ops/deploy_vps.sh
```

Pour redéployer le commit local sans `git pull` :

```bash
./ops/deploy_vps.sh --no-pull
```

Pour ignorer le backup uniquement si un backup récent et vérifié existe déjà :

```bash
./ops/deploy_vps.sh --skip-backup
```

## Notes sécurité

- Ne jamais exposer PostgreSQL publiquement : pas de `ports:` sur `db` en prod.
- Ne jamais commiter `.env.prod`.
- `DJANGO_DEBUG=0` obligatoire.
- HSTS est activé. `DJANGO_SECURE_HSTS_PRELOAD=0` par défaut ; ne passer à `1` que quand tous les sous-domaines sont prêts en HTTPS.
