"""
Data migration: Convert Reparto and StatoInterno from integer/FK references
to inline CharField values before the model changes in the next migration.

This MUST run before the auto-generated migration that alters field types
and deletes the Reparto / StatoInterno models.
"""

from django.db import migrations


# Map old StatoInterno.nome values to new slug-based choices
_STATUS_SLUG_MAP = {
    "Inviato al Cliente": "inviato_al_cliente",
    "Ricevuto": "ricevuto",
    "Da iniziare": "da_iniziare",
    "In lavorazione": "in_lavorazione",
    "In revisione": "in_revisione",
    "In approvazione": "in_approvazione",
    "Concluso": "concluso",
    "Da emettere": "da_emettere",
}


def convert_reparto_and_status(apps, schema_editor):
    """Convert FK/int references to string values using raw SQL,
    while the old tables still exist."""
    from django.db import connection

    with connection.cursor() as cur:
        # ── Documento.Reparto: int → reparto name ─────────────────────
        # Step 1: Add temp VARCHAR column
        cur.execute("ALTER TABLE documenti ADD COLUMN \"Reparto_tmp\" VARCHAR(100) DEFAULT ''")
        # Step 2: Populate from reparti lookup
        cur.execute(
            'UPDATE documenti d SET "Reparto_tmp" = r."Nome" '
            'FROM reparti r WHERE d."Reparto" = r.id'
        )
        # Step 3: Drop old column and rename
        cur.execute('ALTER TABLE documenti DROP COLUMN "Reparto"')
        cur.execute('ALTER TABLE documenti RENAME COLUMN "Reparto_tmp" TO "Reparto"')

        # ── Revisione.IntStatus: FK int → slug string ────────────────
        # Step 1: Drop FK constraint(s) on IntStatus
        cur.execute("""
            DO $$
            DECLARE r RECORD;
            BEGIN
                FOR r IN (
                    SELECT con.conname
                    FROM pg_constraint con
                    JOIN pg_attribute att
                        ON att.attrelid = con.conrelid
                        AND att.attnum = ANY(con.conkey)
                    WHERE con.conrelid = 'revisioni'::regclass
                      AND con.contype = 'f'
                      AND att.attname = 'IntStatus'
                ) LOOP
                    EXECUTE 'ALTER TABLE revisioni DROP CONSTRAINT '
                            || quote_ident(r.conname);
                END LOOP;
            END $$;
        """)

        # Step 2: Add temp VARCHAR column
        cur.execute("ALTER TABLE revisioni ADD COLUMN \"IntStatus_tmp\" VARCHAR(50) DEFAULT ''")
        # Step 3: Populate from stati_interni lookup + slug mapping
        cur.execute('SELECT id, "Nome" FROM stati_interni')
        si_map = {row[0]: row[1] for row in cur.fetchall()}

        for old_id, nome in si_map.items():
            slug = _STATUS_SLUG_MAP.get(nome, nome.lower().replace(" ", "_"))
            cur.execute(
                'UPDATE revisioni SET "IntStatus_tmp" = %s WHERE "IntStatus" = %s',
                [slug, old_id],
            )

        # Step 4: Drop old column and rename
        cur.execute('ALTER TABLE revisioni DROP COLUMN "IntStatus"')
        cur.execute('ALTER TABLE revisioni RENAME COLUMN "IntStatus_tmp" TO "IntStatus"')


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_statoesterno_colore"),
    ]

    operations = [
        migrations.RunPython(
            convert_reparto_and_status,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
