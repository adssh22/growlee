#!/usr/bin/env bash
set -euo pipefail
. .venv/bin/activate
python manage.py makemigrations merchants accounts rewards customers campaigns
