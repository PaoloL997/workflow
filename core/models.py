from django.contrib.auth.models import AbstractUser
from django.db import models


class Stabilimento(models.Model):
    nome = models.CharField(db_column="Nome", max_length=100, unique=True)

    class Meta:
        managed = True
        db_table = "stabilimenti"
        verbose_name = "Stabilimento"
        verbose_name_plural = "Stabilimenti"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Reparto(models.Model):
    nome = models.CharField(db_column="Nome", max_length=100, unique=True)
    acronimo = models.CharField(db_column="Acronimo", max_length=20, blank=True)

    class Meta:
        managed = True
        db_table = "reparti"
        verbose_name = "Reparto"
        verbose_name_plural = "Reparti"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Permesso(models.TextChoices):
    ADMIN = "admin", "Admin"
    WRITING = "writing", "Scrittura"
    READING = "reading", "Lettura"


class User(AbstractUser):
    email = models.EmailField(db_column="Email", unique=True)
    ruolo = models.CharField(db_column="Ruolo", max_length=100, blank=True)
    reparto = models.CharField(db_column="Reparto", max_length=100, blank=True)
    avatar = models.ImageField(db_column="Avatar", upload_to="avatars/", null=True, blank=True)
    permesso = models.CharField(
        db_column="Permesso",
        max_length=20,
        choices=Permesso.choices,
        default=Permesso.READING,
    )
    stabilimento = models.ForeignKey(
        Stabilimento,
        db_column="Stabilimento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="utenti",
    )

    class Meta:
        managed = True
        db_table = "users"
        verbose_name = "Utente"
        verbose_name_plural = "Utenti"

    def __str__(self):
        return self.username

    @property
    def nome_completo(self):
        return self.get_full_name() or self.username

    @property
    def can_write(self):
        return self.permesso in (Permesso.ADMIN, Permesso.WRITING)

    @property
    def is_app_admin(self):
        return self.permesso == Permesso.ADMIN

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.permesso = Permesso.ADMIN
        self.is_staff = self.permesso in (Permesso.ADMIN, Permesso.WRITING)
        super().save(*args, **kwargs)


class Testata(models.Model):
    job = models.CharField(db_column="Job", max_length=50, unique=True)
    client = models.CharField(db_column="Client", max_length=200, blank=True)
    po_no = models.CharField(db_column="PONo", max_length=100, blank=True)
    job_detail = models.CharField(db_column="JobDetail", max_length=300, blank=True)
    delivery_date = models.DateField(db_column="DeliveryDate", blank=True, null=True)
    actual_delivery_date = models.DateField(db_column="ActualDeliveryDate", blank=True, null=True)
    delivery_term = models.CharField(db_column="DeliveryTerm", max_length=200, blank=True)
    requisition = models.CharField(
        db_column="Requisition", max_length=100, blank=True, verbose_name="Bid no."
    )
    time_cli_doc_rev = models.IntegerField(
        db_column="TimeCliDocRev",
        blank=True,
        null=True,
        help_text="Giorni a disposizione del cliente per revisionare un documento.",
    )
    time_ven_doc_rev = models.IntegerField(
        db_column="TimeVenDocRev",
        blank=True,
        null=True,
        help_text="Giorni a nostra disposizione per emettere/revisionare un documento.",
    )
    rev_let_flag = models.BooleanField(db_column="RevLetFlag", default=False)

    class Meta:
        managed = True
        db_table = "testate"
        verbose_name = "Archivio commessa"
        verbose_name_plural = "Archivi commessa"

    def __str__(self):
        return self.job


class AggiornamentoBC(models.Model):
    """Traccia di un campo della testata riallineato a Business Central.

    Una riga per campo modificato dal controllo giornaliero di congruenza
    (vedi ``core.services.bc_sync``).
    """

    testata = models.ForeignKey(
        Testata,
        to_field="job",
        db_column="Job",
        on_delete=models.CASCADE,
        related_name="aggiornamenti_bc",
    )
    campo = models.CharField(db_column="Campo", max_length=50)
    valore_precedente = models.CharField(db_column="ValorePrecedente", max_length=300, blank=True)
    valore_nuovo = models.CharField(db_column="ValoreNuovo", max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "aggiornamenti_bc"
        verbose_name = "Aggiornamento da Business Central"
        verbose_name_plural = "Aggiornamenti da Business Central"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["testata", "created_at"], name="idx_agg_bc_testata_data"),
        ]

    def __str__(self):
        return f"{self.testata_id}: {self.campo}"


class CommessaPin(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="commessa_pins",
    )
    testata = models.ForeignKey(
        Testata,
        to_field="job",
        db_column="Job",
        on_delete=models.CASCADE,
        related_name="pins",
    )
    pinned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "commessa_pins"
        verbose_name = "Pin commessa"
        verbose_name_plural = "Pin commesse"
        ordering = ["pinned_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "testata"],
                name="uniq_user_commessa_pin",
            ),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.testata_id}"


class IndirSped(models.Model):
    testata = models.ForeignKey(
        Testata,
        to_field="job",
        db_column="Job",
        on_delete=models.CASCADE,
        related_name="indirizzi_spedizione",
    )
    consignee = models.CharField(db_column="Consignee", max_length=200, blank=True)
    address = models.CharField(db_column="Address", max_length=300, blank=True)
    zip_code = models.CharField(db_column="ZipCode", max_length=20, blank=True)
    city = models.CharField(db_column="City", max_length=100, blank=True)
    country = models.CharField(db_column="Country", max_length=100, blank=True)
    attn = models.CharField(db_column="Attn", max_length=200, blank=True)
    ph_no = models.CharField(db_column="PhNo", max_length=50, blank=True)

    class Meta:
        managed = True
        db_table = "indirizzi_spedizione"
        verbose_name = "Indirizzo di spedizione"
        verbose_name_plural = "Indirizzi di spedizione"

    def __str__(self):
        parts = [self.consignee, self.city, self.country]
        return " — ".join(p for p in parts if p) or f"Indirizzo #{self.pk}"


# ── Choices for Revisione.int_status (hardcoded, replaces StatoInterno model) ─
STATI_INTERNI_CHOICES = [
    ("da_iniziare", "Da iniziare"),
    ("in_lavorazione", "In lavorazione"),
    ("in_revisione", "In revisione"),
    ("in_approvazione", "In approvazione"),
    ("da_emettere", "Da emettere"),
    ("inviato_al_cliente", "Inviato al Cliente"),
    ("ricevuto", "Ricevuto"),
]


class StatoEsterno(models.Model):
    nome = models.CharField(db_column="Nome", max_length=100, unique=True)
    lettera = models.CharField(
        db_column="Lettera",
        max_length=2,
        blank=True,
        default="",
        verbose_name="Lettera",
        help_text="Codice lettera mostrato in situazione documenti (es. A = Approved).",
    )
    colore = models.CharField(
        db_column="Colore",
        max_length=7,
        blank=True,
        default="",
        help_text="Colore esadecimale (es. #00B050).",
    )
    crea_nuova_rev = models.BooleanField(
        db_column="CreaNuovaRev",
        default=True,
        verbose_name="Crea nuova revisione",
        help_text="Se attivo, alla ricezione con questa risposta viene creata automaticamente una nuova revisione.",
    )

    class Meta:
        managed = True
        db_table = "stati_esterni"
        verbose_name = "Risposta del cliente"
        verbose_name_plural = "Risposte del cliente"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class CartellaModelloDocumento(models.Model):
    nome = models.CharField(
        db_column="Nome",
        max_length=200,
        verbose_name="Nome cartella",
    )
    descrizione = models.TextField(
        db_column="Descrizione",
        blank=True,
        default="",
        verbose_name="Descrizione",
    )

    class Meta:
        managed = True
        db_table = "cartelle_modelli_documento"
        verbose_name = "Cartella modelli documento"
        verbose_name_plural = "Cartelle modelli documento"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class ModelloDocumento(models.Model):
    cartella = models.ForeignKey(
        CartellaModelloDocumento,
        db_column="CartellaId",
        on_delete=models.CASCADE,
        related_name="modelli",
        verbose_name="Cartella",
    )
    doc_title = models.CharField(
        db_column="DocTitle",
        max_length=300,
        verbose_name="Titolo documento",
    )
    item_no = models.CharField(
        db_column="ItemNo",
        max_length=100,
        blank=True,
        default="",
        verbose_name="Item",
    )
    codice_fisso = models.CharField(
        db_column="CodiceFisso",
        max_length=100,
        verbose_name="Codice fisso",
        help_text="Parte fissa del numero documento interno B&R. "
        'Il numero finale sarà "{numero_commessa}-{codice_fisso}".',
    )
    reparto = models.CharField(
        db_column="Reparto",
        max_length=100,
        blank=True,
        default="",
        verbose_name="Reparto",
    )

    class Meta:
        managed = True
        db_table = "modelli_documento"
        verbose_name = "Modello documento"
        verbose_name_plural = "Modelli documento"
        ordering = ["doc_title", "pk"]

    def __str__(self):
        return self.doc_title

    def vendor_doc_for(self, job):
        return f"{job}-{self.codice_fisso}"


class Documento(models.Model):
    testata = models.ForeignKey(
        Testata,
        to_field="job",
        db_column="Job",
        on_delete=models.CASCADE,
        related_name="documenti",
    )
    item_no = models.CharField(db_column="ItemNo", max_length=100, blank=True)
    vendor_doc = models.CharField(db_column="VendorDoc", max_length=200, blank=True)
    client_doc_no = models.CharField(db_column="ClientDocNo", max_length=200, blank=True)
    contractor_doc_no = models.CharField(
        db_column="ContractorDocNo", max_length=200, blank=True, default=""
    )
    client_doc_class = models.CharField(db_column="ClientDocClass", max_length=200, blank=True)
    doc_title = models.CharField(db_column="DocTitle", max_length=300, blank=True)
    doc_penalty = models.BooleanField(db_column="DocPenalty", default=False)
    doc_payment = models.BooleanField(db_column="DocPayment", default=False)
    rev_gen = models.BooleanField(db_column="RevGen", default=False)
    reparto = models.CharField(
        db_column="Reparto",
        max_length=100,
        blank=True,
        default="",
        help_text="Nome del reparto responsabile.",
    )
    remarks = models.TextField(db_column="Remarks", blank=True)

    class Meta:
        managed = True
        db_table = "documenti"
        verbose_name = "Documento"
        verbose_name_plural = "Documenti"

    def __str__(self):
        return f"{self.testata_id} — {self.doc_title or self.pk}"


class Revisione(models.Model):
    documento = models.ForeignKey(
        Documento,
        db_column="IdDoc",
        on_delete=models.CASCADE,
        related_name="revisioni",
    )
    rev_no = models.IntegerField(db_column="RevNo", blank=True, null=True)
    rev_let = models.CharField(db_column="RevLet", max_length=10, blank=True)
    dis_plan_date = models.DateField(db_column="DisPlanDate", blank=True, null=True)
    dis_act_date = models.DateField(db_column="DisActDate", blank=True, null=True)
    rec_plan_date = models.DateField(db_column="RecPlanDate", blank=True, null=True)
    rec_act_date = models.DateField(db_column="RecActDate", blank=True, null=True)
    int_status = models.CharField(
        db_column="IntStatus",
        max_length=50,
        blank=True,
        default="",
        choices=STATI_INTERNI_CHOICES,
    )
    ext_status = models.ForeignKey(
        StatoEsterno,
        db_column="ExtStatus",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="revisioni",
    )
    crea_nuova_rev = models.BooleanField(
        db_column="CreaNuovaRev",
        default=False,
        help_text="Flag per creare una nuova revisione al rientro dal cliente.",
    )
    ignora_anomalie = models.BooleanField(
        db_column="IgnoraAnomalie",
        default=False,
        help_text="Se attivo, le incongruenze su questa revisione non vengono segnalate.",
    )

    class Meta:
        managed = True
        db_table = "revisioni"
        verbose_name = "Revisione"
        verbose_name_plural = "Revisioni"
        ordering = ["rev_no"]

    def etichetta(self):
        """Lettera o numero della revisione, secondo il flag della testata."""
        from .services.revisione_label import format_revisione_label

        return format_revisione_label(
            self.rev_no, self.rev_let, self.documento.testata.rev_let_flag
        )

    def __str__(self):
        etichetta = self.etichetta()
        return f"Rev {etichetta}" if etichetta else f"Rev #{self.pk}"


class RevisioneFileLink(models.Model):
    """Manual file link for a revision when auto-resolution fails."""

    revisione = models.OneToOneField(
        Revisione,
        on_delete=models.CASCADE,
        related_name="file_link",
    )
    percorso = models.CharField(
        db_column="Percorso",
        max_length=500,
        help_text="Percorso completo al file sul fileserver.",
    )
    created_at = models.DateTimeField(db_column="CreatedAt", auto_now_add=True)
    updated_at = models.DateTimeField(db_column="UpdatedAt", auto_now=True)

    class Meta:
        managed = True
        db_table = "revisioni_file_link"
        verbose_name = "Link file revisione"
        verbose_name_plural = "Link file revisioni"

    def __str__(self):
        return f"{self.revisione} → {self.percorso}"


class Transmittal(models.Model):
    """Issued transmittal for a job, archived on the fileserver."""

    testata = models.ForeignKey(
        Testata,
        to_field="job",
        db_column="Job",
        on_delete=models.CASCADE,
        related_name="trasmittal",
    )
    numero = models.PositiveIntegerField(db_column="Numero")
    data_emissione = models.DateField(db_column="DataEmissione", blank=True, null=True)
    revisioni = models.ManyToManyField(
        Revisione,
        blank=True,
        related_name="trasmittal",
        db_table="trasmittal_revisioni",
    )

    class Meta:
        managed = True
        db_table = "trasmittal"
        verbose_name = "Transmittal"
        verbose_name_plural = "Transmittal"
        unique_together = ("testata", "numero")
        ordering = ["-numero"]

    def __str__(self):
        return f"Transmittal {self.codice}"

    @property
    def codice(self) -> str:
        return f"{self.testata_id}-{self.numero}"


class TipoSegnalazione(models.TextChoices):
    FEATURE = "feature", "Feature"
    PROBLEMA = "problema", "Problema"


class StatoSegnalazione(models.TextChoices):
    APERTO = "aperto", "Aperto"
    CHIUSO = "chiuso", "Chiuso"


class Segnalazione(models.Model):
    autore = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="segnalazioni",
    )
    tipo = models.CharField(max_length=20, choices=TipoSegnalazione.choices)
    titolo = models.CharField(max_length=200)
    testo = models.TextField()
    stato = models.CharField(
        max_length=20,
        choices=StatoSegnalazione.choices,
        default=StatoSegnalazione.APERTO,
    )
    chiuso_da = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="segnalazioni_chiuse",
    )
    chiuso_il = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "segnalazioni"
        verbose_name = "Segnalazione"
        verbose_name_plural = "Segnalazioni"
        ordering = ["-created_at"]

    def __str__(self):
        return self.titolo


class SegnalazioneVoto(models.Model):
    segnalazione = models.ForeignKey(
        Segnalazione,
        on_delete=models.CASCADE,
        related_name="voti",
    )
    utente = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="segnalazione_voti",
    )
    valore = models.SmallIntegerField()

    class Meta:
        managed = True
        db_table = "segnalazione_voti"
        verbose_name = "Voto segnalazione"
        verbose_name_plural = "Voti segnalazioni"
        constraints = [
            models.UniqueConstraint(
                fields=["segnalazione", "utente"],
                name="uniq_utente_segnalazione_voto",
            ),
        ]

    def __str__(self):
        return f"{self.utente_id}:{self.segnalazione_id}={self.valore}"


class Notifica(models.Model):
    """In-app notification shown in the bell menu, one row per recipient."""

    destinatario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifiche",
    )
    segnalazione = models.ForeignKey(
        Segnalazione,
        on_delete=models.CASCADE,
        related_name="notifiche",
    )
    testo = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    letta_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = True
        db_table = "notifiche"
        verbose_name = "Notifica"
        verbose_name_plural = "Notifiche"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["destinatario", "segnalazione"],
                name="uniq_destinatario_segnalazione_notifica",
            ),
        ]
        indexes = [
            models.Index(fields=["destinatario", "letta_il"], name="idx_notifica_dest_letta"),
        ]

    def __str__(self):
        return f"{self.destinatario_id}: {self.testo}"


class SegnalazioneCommento(models.Model):
    segnalazione = models.ForeignKey(
        Segnalazione,
        on_delete=models.CASCADE,
        related_name="commenti",
    )
    autore = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="segnalazione_commenti",
    )
    testo = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "segnalazione_commenti"
        verbose_name = "Commento segnalazione"
        verbose_name_plural = "Commenti segnalazioni"
        ordering = ["created_at"]

    def __str__(self):
        return f"Commento #{self.pk}"


class EsecuzioneSchedulata(models.Model):
    """Ultima esecuzione di un lavoro periodico avviato dall'applicazione.

    Una riga per lavoro (vedi ``core.services.scheduler``). Vive in database e
    non in memoria perché è ciò che garantisce una sola esecuzione al giorno
    anche quando il sito gira su più processi o viene riavviato.
    """

    nome = models.CharField(primary_key=True, max_length=50)
    ultima_esecuzione = models.DateTimeField(null=True, blank=True)
    esito = models.CharField(max_length=300, blank=True)

    class Meta:
        managed = True
        db_table = "esecuzioni_schedulate"
        verbose_name = "Esecuzione schedulata"
        verbose_name_plural = "Esecuzioni schedulate"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome}: {self.ultima_esecuzione or 'mai eseguito'}"
