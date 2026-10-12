"""Storage degli statici in produzione: WhiteNoise con manifest, ma senza bloccare.

``CompressedManifestStaticFilesStorage`` serve ogni file con un hash nel nome
(cache lunga, versione nuova a ogni deploy) e in versione compressa. Se però
``collectstatic`` non è stato rilanciato dopo un ``git pull``, un file assente
dal manifest (o da ``staticfiles/``) farebbe fallire il rendering di ogni
pagina che lo cita. Qui si preferisce ricadere sul nome semplice: la pagina si
vede, al massimo senza cache lunga (WhiteNoise lo serve tramite i finder, vedi
``WHITENOISE_USE_FINDERS`` in settings).
"""

from whitenoise.storage import CompressedManifestStaticFilesStorage


class StaticFilesStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False

    def stored_name(self, name):
        try:
            return super().stored_name(name)
        except ValueError:
            # Non nel manifest e non in STATIC_ROOT: collectstatic non è stato
            # lanciato. Nome semplice, niente errore.
            return name
