"""Backend SMTP che valida i certificati TLS con il bundle CA di certifi.

Su Windows, Python legge i certificati CA di sistema solo dallo store
"Utente corrente" (``ssl.enum_certificates`` usa sempre
``CERT_SYSTEM_STORE_CURRENT_USER``), mai da "Computer locale". L'account
di servizio che esegue l'app (identità virtuale dell'app pool IIS) ha un
profilo Windows proprio, quasi sempre privo dei certificati intermedi/radice
necessari per validare server SMTP che non inviano la catena completa
nell'handshake (es. Aruba, CA Actalis) — da cui ``CERTIFICATE_VERIFY_FAILED:
unable to get local issuer certificate``, non riproducibile da un utente
interattivo con uno store più popolato.

Usare il bundle di certifi rende la verifica indipendente da quale account
Windows esegue il processo.
"""

import ssl

import certifi
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend


class EmailBackend(SMTPEmailBackend):
    @property
    def ssl_context(self):
        if self.ssl_certfile or self.ssl_keyfile:
            return super().ssl_context
        return ssl.create_default_context(cafile=certifi.where())
