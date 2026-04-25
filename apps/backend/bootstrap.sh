#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python manage.py makemigrations merchants campaigns customers
