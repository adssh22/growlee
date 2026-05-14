# Growlee — infra hardening runbook

> À appliquer sur le VPS avec prudence. Ne jamais fermer SSH sans avoir une console fournisseur ouverte.

## 1. Firewall strict

Profil VPS classique avec Nginx/Caddy devant Django :

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp comment 'SSH'
sudo ufw allow 80/tcp comment 'HTTP ACME redirect'
sudo ufw allow 443/tcp comment 'HTTPS'
sudo ufw enable
sudo ufw status verbose
```

Si SSH est sur un autre port, remplacer `22/tcp` avant `ufw enable`.

## 2. SSH clé uniquement

Vérifier d’abord que la connexion par clé fonctionne dans une deuxième session.

```bash
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%Y%m%d%H%M)
sudo install -m 644 /etc/ssh/sshd_config /tmp/sshd_config.growlee
sudo sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication no/' /tmp/sshd_config.growlee
sudo sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /tmp/sshd_config.growlee
sudo sshd -t -f /tmp/sshd_config.growlee
sudo cp /tmp/sshd_config.growlee /etc/ssh/sshd_config
sudo systemctl reload ssh
```

Rollback : restaurer le backup puis `sudo systemctl reload ssh`.

## 3. Fail2ban

```bash
sudo apt-get update
sudo apt-get install -y fail2ban
sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd
```

## 4. Mises à jour sécurité auto

```bash
sudo apt-get install -y unattended-upgrades apt-listchanges
sudo dpkg-reconfigure -plow unattended-upgrades
systemctl status unattended-upgrades --no-pager
```

## 5. Reverse proxy HTTPS

Nginx doit transmettre les headers proxy utilisés par Django :

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}
```

Django prod :

```env
DJANGO_DEBUG=0
DJANGO_SECURE_SSL_REDIRECT=1
DJANGO_SESSION_COOKIE_SECURE=1
DJANGO_CSRF_COOKIE_SECURE=1
DJANGO_SECURE_HSTS_SECONDS=31536000
```

## 6. Backups

Script inclus : `ops/backup_postgres.sh`.

Exemple cron quotidien :

```cron
17 2 * * * DATABASE_URL='postgresql://...' BACKUP_DIR=/var/backups/growlee/postgres /srv/growlee/ops/backup_postgres.sh >> /var/log/growlee-backup.log 2>&1
```

Tester une restauration avec `ops/restore_check_postgres.sh` sur une base jetable.

## 7. Monitoring minimal

Script inclus : `ops/monitoring_check.sh`.
À brancher dans cron/monitoring externe avec alertes sur code retour non zéro.

À surveiller : disque, RAM, CPU/load, taille DB, expiration SSL, erreurs app, erreurs Nginx, backups récents.
