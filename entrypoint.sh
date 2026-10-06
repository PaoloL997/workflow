#!/bin/sh
set -eu

python - <<'PY'
import os
import sys
import time

import psycopg2

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    print("DATABASE_URL mancante.", file=sys.stderr)
    sys.exit(1)

for attempt in range(1, 31):
    try:
        connection = psycopg2.connect(database_url)
        connection.close()
        break
    except psycopg2.OperationalError as exc:
        if attempt == 30:
            print(f"Database non raggiungibile: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"Attendo PostgreSQL ({attempt}/30)...")
        time.sleep(2)
PY

# Con lo storage S3 configurato (servizio `storage` del compose) si aspetta che
# il bucket risponda: Garage crea chiave e bucket qualche secondo dopo l'avvio.
python - <<'PY'
import os
import sys
import time

if not os.environ.get("S3_BUCKET"):
    sys.exit(0)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from botocore.exceptions import BotoCoreError, ClientError
from django.core.files.storage import default_storage

client = default_storage.connection.meta.client
for attempt in range(1, 31):
    try:
        client.head_bucket(Bucket=default_storage.bucket_name)
        break
    except (BotoCoreError, ClientError) as exc:
        if attempt == 30:
            print(f"Storage S3 non raggiungibile: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"Attendo lo storage S3 ({attempt}/30)...")
        time.sleep(2)
PY

python manage.py migrate --noinput

# Foto profilo e firme caricate prima dello storage S3: si copiano dal volume
# media nel bucket. Idempotente (salta i file già copiati), non blocca l'avvio.
if [ -n "${S3_BUCKET:-}" ] && [ -n "$(ls -A /app/media 2>/dev/null)" ]; then
    python manage.py copia_media_su_storage \
        || echo "Copia dei file media su S3 non riuscita (vedi sopra)." >&2
fi

python manage.py collectstatic --noinput

exec "$@"
