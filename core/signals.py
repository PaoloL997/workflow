from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.models import User
from core.services.media import elimina_file


@receiver(post_delete, sender=User)
def elimina_media_utente(sender, instance, **kwargs):
    """Cancella foto profilo e firma di un utente eliminato.

    Django non cancella i file dei ``FileField``. Si aspetta il commit: se
    l'eliminazione viene annullata i file devono restare.
    """
    nomi = [instance.avatar.name, instance.firma.name]
    transaction.on_commit(lambda: elimina_file(nomi))
