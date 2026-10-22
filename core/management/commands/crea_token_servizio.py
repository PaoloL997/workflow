"""Emette il token senza scadenza di un utente di servizio (es. ``workflow-agent``).

Un servizio esterno che non agisce per conto di una persona, come l'ingestion
schedulata di workflow-agent che legge ``GET /api/manuale/``, non può dipendere
da un token che scade dopo una sessione. Usa il token di un utente di servizio
(gruppo "Servizio", vedi ``core.permissions.is_service_user``): sola lettura,
niente login via sessione, nessuna scadenza.

Ogni esecuzione revoca i token precedenti dell'utente e ne crea uno nuovo: la
chiave in chiaro esce solo qui, una volta, e nel database resta solo l'hash.
Con ``--revoca`` elimina i token senza crearne uno nuovo.
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.management.utf8 import forza_utf8
from core.models import ApiToken, Permesso, User
from core.permissions import GRUPPO_SERVIZIO, is_service_user


class Command(BaseCommand):
    help = (
        "Crea l'utente di servizio se non esiste, revoca i suoi token e ne emette uno "
        "senza scadenza, mostrando la chiave una sola volta. Con --revoca elimina "
        "soltanto i token dell'utente."
    )

    def add_arguments(self, parser):
        parser.add_argument("username", help="Utente di servizio, es. workflow-agent.")
        parser.add_argument(
            "--revoca",
            action="store_true",
            help="Elimina tutti i token dell'utente senza crearne uno nuovo.",
        )

    def handle(self, *args, **options):
        forza_utf8(self.stdout)
        forza_utf8(self.stderr)
        username = options["username"].strip()
        if not username:
            raise CommandError("Indica lo username dell'utente di servizio.")
        if options["revoca"]:
            self._revoca(username)
        else:
            self._crea_token(username)

    def _revoca(self, username):
        user = User.objects.filter(username=username).first()
        if user is None:
            raise CommandError(f'L\'utente "{username}" non esiste.')
        revocati, _ = user.api_tokens.all().delete()
        self.stdout.write(self.style.SUCCESS(f'Token revocati per "{username}": {revocati}.'))

    def _crea_token(self, username):
        # La chiave si stampa solo dopo il commit: una stampata e poi persa col
        # rollback non varrebbe niente.
        with transaction.atomic():
            user = self._utente_di_servizio(username)
            revocati, _ = user.api_tokens.all().delete()
            _, chiave = ApiToken.crea_per_utente(user, senza_scadenza=True)
        if revocati:
            self.stdout.write(f"Token precedenti revocati: {revocati}.")
        self.stdout.write(self.style.SUCCESS(f'Token senza scadenza per "{username}":'))
        self.stdout.write("")
        self.stdout.write(f"    {chiave}")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "La chiave non verrà più mostrata: nel database resta solo il suo hash. "
                "Copiala ora (es. WORKFLOW_TOKEN nel .env di workflow-agent)."
            )
        )

    def _utente_di_servizio(self, username):
        """L'utente di servizio ``username``, creato se non esiste.

        Un utente che esiste già ma non è di servizio non viene convertito: con
        uno username sbagliato si toglierebbero scrittura, login e token a una
        persona.
        """
        user = User.objects.filter(username=username).first()
        if user is None:
            # Email vuota: un utente di servizio non riceve email, e così resta
            # fuori dai suggerimenti degli indirizzi del trasmittal interno. Ma
            # il campo è unico, quindi può averla vuota un solo utente.
            if User.objects.filter(email="").exists():
                raise CommandError(
                    "Un altro utente ha già l'email vuota (il campo è unico): crea questo "
                    "utente dall'admin con un'email propria, aggiungilo al gruppo "
                    f'"{GRUPPO_SERVIZIO}" e rilancia il comando.'
                )
            user = User(username=username, email="", permesso=Permesso.READING, is_active=True)
            user.set_unusable_password()
            user.save()
            self.stdout.write(f'Utente "{username}" creato.')
        elif not is_service_user(user):
            raise CommandError(
                f'L\'utente "{username}" esiste e non è di servizio: non lo converto. '
                f'Se è davvero un utente di servizio, aggiungilo al gruppo "{GRUPPO_SERVIZIO}" '
                "dall'admin e rilancia il comando."
            )
        elif not user.is_active:
            raise CommandError(
                f"L'utente \"{username}\" è disattivato: riattivalo dall'admin e rilancia "
                "il comando, altrimenti il token non varrebbe."
            )
        else:
            # Anche se nel frattempo qualcuno gli avesse dato una password.
            user.set_unusable_password()
            user.save(update_fields=["password"])
        gruppo, _ = Group.objects.get_or_create(name=GRUPPO_SERVIZIO)
        user.groups.add(gruppo)
        return user
