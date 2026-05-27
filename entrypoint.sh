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

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
