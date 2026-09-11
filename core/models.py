from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


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


FIRMA_MAX_BYTE = 1024 * 1024
FIRMA_FORMATI = ("PNG", "JPEG")


def valida_immagine_firma(file):
    """L'immagine di firma: un PNG o un JPEG veri, al massimo 1 MB.

    Il formato si legge dal contenuto e non dal nome: un ".png" che non è
    un'immagine si rifiuta. Il caso previsto è un PNG con lo sfondo
    trasparente, che si posa bene su qualsiasi colore.
    """
    from PIL import Image, UnidentifiedImageError

    if file.size > FIRMA_MAX_BYTE:
        raise ValidationError("L'immagine di firma può pesare al massimo 1 MB.")
    try:
        file.seek(0)
        with Image.open(file) as immagine:
            formato = immagine.format
            immagine.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ValidationError(
            "Il file non è un'immagine valida: carica un PNG, meglio se trasparente, o un JPEG."
        ) from None
    finally:
        file.seek(0)
    if formato not in FIRMA_FORMATI:
        raise ValidationError(
            "Formato non ammesso: carica un PNG, meglio se trasparente, o un JPEG."
        )


class User(AbstractUser):
    email = models.EmailField(db_column="Email", unique=True)
    ruolo = models.CharField(db_column="Ruolo", max_length=100, blank=True)
    reparto = models.CharField(db_column="Reparto", max_length=100, blank=True)
    avatar = models.ImageField(db_column="Avatar", upload_to="avatars/", null=True, blank=True)
    # Compare sugli step del Quality Control Plan che l'utente firma, e serve per
    # firmarli: senza non si firma (vedi ``firma_punto``). Se l'utente la toglie,
    # le sue firme già registrate mostrano nome e data al posto dell'immagine.
    firma = models.ImageField(
        db_column="Firma",
        upload_to="firme/",
        null=True,
        blank=True,
        validators=[valida_immagine_firma],
        verbose_name="Immagine di firma",
    )
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


class QualityControlPlan(models.Model):
    """Testata di un piano dei controlli qualità, congelata alla creazione.

    I dati anagrafici arrivano da Business Central quando il piano viene creato e
    da lì restano fermi: BC cambia nel tempo e contiene refusi che l'utente
    corregge a mano, ma un documento emesso deve restare identico a com'era.

    Vendor e Job N° non sono colonne: il primo è una costante uguale su ogni riga,
    il secondo è ``testata_id``. Salvarli sarebbe duplicare un dato che non può
    divergere. Il titolo invece è una colonna: si propone come
    ``{job}-QCP{lettera}`` ma l'utente può cambiarlo, quindi va conservato.
    """

    testata = models.ForeignKey(
        Testata,
        to_field="job",
        db_column="Job",
        on_delete=models.CASCADE,
        related_name="quality_control_plans",
    )
    titolo = models.CharField(db_column="Titolo", max_length=200, blank=True)
    # Doc n., Dwg n. e Serial n. si calcolano (vedi ``doc_no_calcolato`` e
    # simili): la colonna serve solo a chi vuole un numero diverso, e ai piani
    # emessi prima che la regola esistesse. Valorizzata, vince sul calcolo.
    doc_no = models.CharField(
        db_column="DocNo",
        max_length=100,
        blank=True,
        verbose_name="Doc n.",
        help_text="Vuoto: si usa il numero calcolato.",
    )
    location = models.CharField(db_column="Location", max_length=200, blank=True)
    # Foglio del QCP stesso, da non confondere con ``foglio_dwg``.
    sheet = models.CharField(
        db_column="Sheet", max_length=50, blank=True, verbose_name="Foglio QCP"
    )
    project = models.CharField(db_column="Project", max_length=300, blank=True)
    dwg_no = models.CharField(
        db_column="DwgNo",
        max_length=100,
        blank=True,
        verbose_name="Dwg n.",
        help_text="Vuoto: si usa il numero calcolato.",
    )
    owner = models.CharField(db_column="Owner", max_length=200, blank=True)
    po_no = models.CharField(db_column="PONo", max_length=100, blank=True, verbose_name="PO n.")
    data = models.DateField(db_column="Data", null=True, blank=True)
    purchaser = models.CharField(db_column="Purchaser", max_length=200, blank=True)
    descrizione_item = models.CharField(db_column="DescrizioneItem", max_length=300, blank=True)
    serial_no = models.CharField(
        db_column="SerialNo",
        max_length=100,
        blank=True,
        verbose_name="Serial n.",
        help_text="Vuoto: si usa il numero calcolato.",
    )
    # Componenti grezzi della numerazione, come nel foglio DATI dell'Excel.
    dwg_base = models.CharField(
        db_column="DwgBase", max_length=20, blank=True, verbose_name="Dwg n. (base)"
    )
    serial_base = models.CharField(
        db_column="SerialBase", max_length=20, blank=True, verbose_name="Serial n. (base)"
    )
    foglio_dwg = models.CharField(
        db_column="FoglioDwg", max_length=20, blank=True, verbose_name="Foglio disegno n."
    )
    rev_no = models.PositiveSmallIntegerField(db_column="RevNo", default=0, verbose_name="Rev n.")
    mdmt = models.CharField(db_column="MDMT", max_length=50, blank=True, verbose_name="MDMT")
    asme_stamp = models.BooleanField(
        db_column="AsmeStamp", default=False, verbose_name="ASME stamp"
    )
    national_board = models.BooleanField(
        db_column="NationalBoard", default=False, verbose_name="National Board"
    )
    lethal_service = models.BooleanField(
        db_column="LethalService", default=False, verbose_name="Lethal service"
    )
    h2s_service = models.BooleanField(
        db_column="H2SService", default=False, verbose_name="H2S service"
    )
    notification_advice_time = models.CharField(
        db_column="NotificationAdviceTime",
        max_length=200,
        blank=True,
        verbose_name="Notification advice time",
    )
    prepared_by = models.CharField(db_column="PreparedBy", max_length=200, blank=True)
    prepared_by_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quality_control_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        managed = True
        db_table = "quality_control_plan"
        verbose_name = "Quality Control Plan"
        verbose_name_plural = "Quality Control Plan"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["testata", "created_at"], name="idx_qcp_testata_data"),
        ]

    def __str__(self):
        return self.titolo or f"{self.testata_id} — QCP {self.doc_no_effettivo or self.pk}"

    # La numerazione sta sul modello e non nel service perché dipende solo dai
    # campi della riga: nessuna query e nessun ERP, come invece serve al titolo
    # proposto, che deve guardare gli altri piani della commessa. Così la
    # leggono allo stesso modo serializzazione, admin e ``__str__``. Non è
    # persistita: cambiare un componente cambia il numero, senza colonne da
    # tenere allineate. Le regole sono quelle del foglio DATI (B33/B34/B35).

    def _numero(self, sigla, suffisso):
        """``{job}-{dwg_base}-{sigla}{suffisso}``, o vuoto se manca un pezzo.

        Meglio nessun numero che uno malformato come ``26026--QCP``: un campo
        vuoto si nota e si compila, un numero sbagliato finisce stampato.
        """
        job = (self.testata_id or "").strip()
        base = (self.dwg_base or "").strip()
        suffisso = (suffisso or "").strip()
        if not (job and base and suffisso):
            return ""
        return f"{job}-{base}-{sigla}{suffisso}"

    @property
    def doc_no_calcolato(self):
        return self._numero("QCP", self.serial_base)

    @property
    def dwg_no_calcolato(self):
        return self._numero("EGA", self.foglio_dwg)

    @property
    def serial_no_calcolato(self):
        return self._numero("SN", self.serial_base)

    @property
    def doc_no_effettivo(self):
        return (self.doc_no or "").strip() or self.doc_no_calcolato

    @property
    def dwg_no_effettivo(self):
        return (self.dwg_no or "").strip() or self.dwg_no_calcolato

    @property
    def serial_no_effettivo(self):
        return (self.serial_no or "").strip() or self.serial_no_calcolato


class QualityControlPlanItem(models.Model):
    """Item coperto da un Quality Control Plan.

    Un piano può coprire più item, quindi gli item stanno su righe proprie invece
    che dentro un'unica stringa separata da "/", che è il problema che ha oggi
    ``Documento.item_no``.
    """

    piano = models.ForeignKey(
        QualityControlPlan,
        db_column="IdQCP",
        on_delete=models.CASCADE,
        related_name="items",
    )
    item_no = models.CharField(db_column="ItemNo", max_length=200, verbose_name="Item")
    descrizione = models.CharField(db_column="Descrizione", max_length=300, blank=True)
    ordine = models.PositiveSmallIntegerField(db_column="Ordine", default=0)

    class Meta:
        managed = True
        db_table = "quality_control_plan_items"
        verbose_name = "Item del Quality Control Plan"
        verbose_name_plural = "Item del Quality Control Plan"
        ordering = ["ordine", "id"]
        constraints = [
            models.UniqueConstraint(fields=["piano", "item_no"], name="uniq_qcp_item"),
        ]

    def __str__(self):
        return self.item_no


class QualityControlPlanCode(models.Model):
    """Codice applicabile di un Quality Control Plan ("Applicable Code" in cover).

    Il valore è libero: il modulo propone i codici più usati, ma nell'Excel la
    cella non è vincolata e un codice fuori elenco deve restare possibile, quindi
    niente ``choices``. Il massimo di righe, come per spec ed enti, lo applica il
    service e non il database.
    """

    piano = models.ForeignKey(
        QualityControlPlan,
        db_column="IdQCP",
        on_delete=models.CASCADE,
        related_name="codes",
    )
    codice = models.CharField(db_column="Codice", max_length=200, verbose_name="Codice")
    ordine = models.PositiveSmallIntegerField(db_column="Ordine", default=0)

    class Meta:
        managed = True
        db_table = "quality_control_plan_codes"
        verbose_name = "Codice applicabile del Quality Control Plan"
        verbose_name_plural = "Codici applicabili del Quality Control Plan"
        ordering = ["ordine", "id"]
        constraints = [
            models.UniqueConstraint(fields=["piano", "codice"], name="uniq_qcp_code"),
        ]

    def __str__(self):
        return self.codice


class QualityControlPlanSpec(models.Model):
    """Specifica del cliente richiamata da un Quality Control Plan ("Client Spec.s").

    Testo libero e senza elenco proposto: sono riferimenti del cliente, come
    "Req. nr. L001-00000-MS-7303-1002" o "and all specs listed in above req.".
    """

    piano = models.ForeignKey(
        QualityControlPlan,
        db_column="IdQCP",
        on_delete=models.CASCADE,
        related_name="specs",
    )
    spec = models.CharField(db_column="Spec", max_length=300, verbose_name="Spec")
    ordine = models.PositiveSmallIntegerField(db_column="Ordine", default=0)

    class Meta:
        managed = True
        db_table = "quality_control_plan_specs"
        verbose_name = "Specifica cliente del Quality Control Plan"
        verbose_name_plural = "Specifiche cliente del Quality Control Plan"
        ordering = ["ordine", "id"]
        constraints = [
            models.UniqueConstraint(fields=["piano", "spec"], name="uniq_qcp_spec"),
        ]

    def __str__(self):
        return self.spec


class QualityControlPlanAgency(models.Model):
    """Ente di ispezione di un Quality Control Plan ("Inspection Agencies").

    L'ordine non è estetico. Ogni ente diventerà una colonna del corpo del piano,
    dove ciascuno step avrà un punto d'intervento (W/H/R/SW/M/A) per ogni ente:
    ``ordine`` è la posizione di quella colonna, e cambiarlo sposta la colonna.
    Per lo stesso motivo gli enti sono righe proprie e non un elenco dentro un
    campo: gli interventi dovranno poter puntare all'ente. Il primo è di solito
    il vendor stesso, "B&R".
    """

    piano = models.ForeignKey(
        QualityControlPlan,
        db_column="IdQCP",
        on_delete=models.CASCADE,
        related_name="agencies",
    )
    nome = models.CharField(db_column="Nome", max_length=200, verbose_name="Ente")
    ordine = models.PositiveSmallIntegerField(db_column="Ordine", default=0)

    class Meta:
        managed = True
        db_table = "quality_control_plan_agencies"
        verbose_name = "Ente di ispezione del Quality Control Plan"
        verbose_name_plural = "Enti di ispezione del Quality Control Plan"
        ordering = ["ordine", "id"]
        constraints = [
            models.UniqueConstraint(fields=["piano", "nome"], name="uniq_qcp_agency"),
        ]

    def __str__(self):
        return self.nome


class AttivitaQCP(models.Model):
    """Attività del catalogo del Quality Control Plan: anagrafica globale.

    Nell'Excel stavano in un foglio d'appoggio che il piano richiamava per
    codice; qui sono una tabella uguale per tutte le commesse, mantenuta
    dall'admin. Il codice non è univoco (la stessa attività compare in capitoli
    diversi), quindi la chiave è l'id e l'unicità è su codice + capitolo.

    Un'attività non si cancella mai: si disattiva con ``attivo``, così i piani
    che la useranno restano leggibili anche quando esce dal catalogo.
    """

    class TipoRiferimento(models.TextChoices):
        SUFFISSO_JOB = "suffisso_job", "Job + suffisso"
        STATICO = "statico", "Statico"
        COMPOSITO = "composito", "Composito"
        CAMPO_PIANO = "campo_piano", "Campo del piano"
        DA_PROC = "da_proc", "Da matrice saldature"

    # Campi del piano che un riferimento "campo_piano" può richiamare: il numero
    # effettivo, cioè quello scritto a mano se c'è, altrimenti quello calcolato.
    _CAMPI_PIANO = {"dwg_no": "dwg_no_effettivo", "doc_no": "doc_no_effettivo"}

    codice = models.CharField(db_column="Codice", max_length=200, verbose_name="Codice")
    divisione = models.CharField(db_column="Divisione", max_length=20, verbose_name="Divisione")
    capitolo = models.CharField(db_column="Capitolo", max_length=100, verbose_name="Capitolo")
    descrizione = models.CharField(
        db_column="Descrizione", max_length=300, verbose_name="Descrizione"
    )
    test_inspection = models.CharField(
        db_column="TestInspection", max_length=200, blank=True, verbose_name="Test / inspection"
    )
    reference_doc_tipo = models.CharField(
        db_column="ReferenceDocTipo",
        max_length=20,
        choices=TipoRiferimento.choices,
        verbose_name="Tipo di riferimento",
        help_text="Come si costruisce il riferimento B&R per una commessa.",
    )
    reference_doc_valore = models.CharField(
        db_column="ReferenceDocValore",
        max_length=200,
        blank=True,
        verbose_name="Riferimento",
        help_text=(
            'Suffisso del job ("/PT"), testo fisso, parti separate da "|", nome di '
            "un campo del piano (dwg_no, doc_no) secondo il tipo."
        ),
    )
    acceptance_criteria = models.CharField(
        db_column="AcceptanceCriteria",
        max_length=300,
        blank=True,
        verbose_name="Acceptance criteria",
    )
    documento_richiesto = models.CharField(
        db_column="DocumentoRichiesto",
        max_length=200,
        blank=True,
        verbose_name="Documento richiesto",
    )
    tecnica = models.CharField(
        db_column="Tecnica", max_length=50, blank=True, verbose_name="Tecnica"
    )
    tipo = models.CharField(db_column="Tipo", max_length=20, blank=True, verbose_name="Tipo")
    ordine = models.PositiveSmallIntegerField(db_column="Ordine", verbose_name="Ordine")
    attivo = models.BooleanField(db_column="Attivo", default=True, verbose_name="Attiva")

    class Meta:
        managed = True
        db_table = "attivita_qcp"
        verbose_name = "Attività del catalogo QCP"
        verbose_name_plural = "Catalogo attività QCP"
        ordering = ["ordine", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["codice", "capitolo"], name="uniq_attivita_qcp_cod_cap"
            ),
        ]
        indexes = [
            models.Index(fields=["capitolo"], name="idx_attivita_qcp_capitolo"),
            models.Index(fields=["divisione"], name="idx_attivita_qcp_divisione"),
            models.Index(fields=["tipo"], name="idx_attivita_qcp_tipo"),
            # Niente GIN con pg_trgm: l'estensione non è verificata in tutti gli
            # ambienti. Btree su descrizione e ricerca con icontains, che per
            # qualche centinaio di righe è più che sufficiente.
            models.Index(fields=["descrizione"], name="idx_attivita_qcp_descrizione"),
        ]

    def __str__(self):
        return f"{self.codice} ({self.capitolo})"

    def risolvi_reference_doc(self, piano):
        """Il riferimento B&R di questa attività per un piano, o "" se non si può.

        È l'unico punto che sa come si costruisce il riferimento:

        - ``suffisso_job``: job + valore, "26026" + "/PT" → "26026/PT";
        - ``statico``: il valore così com'è;
        - ``composito``: parti separate da "|" unite da uno spazio; la prima è un
          prefisso fisso se non comincia per "/" o "-", le altre sono suffissi
          del job: "BCI-006-CWC|-TMRS" → "BCI-006-CWC 26026-TMRS";
        - ``campo_piano``: il valore del campo del piano indicato (dwg_no, doc_no);
        - ``da_proc``: dipende dalla matrice saldature, non ancora modellata.

        Senza piano, o senza i dati che servono (job, campo del piano), il
        riferimento è vuoto: meglio nessun numero che uno incompleto.
        """
        if piano is None:
            return ""
        job = str(getattr(piano, "testata_id", "") or "").strip()
        valore = (self.reference_doc_valore or "").strip()
        tipo = self.reference_doc_tipo

        if tipo == self.TipoRiferimento.STATICO:
            return valore
        if tipo == self.TipoRiferimento.SUFFISSO_JOB:
            return f"{job}{valore}" if job and valore else ""
        if tipo == self.TipoRiferimento.COMPOSITO:
            parti = [parte.strip() for parte in valore.split("|") if parte.strip()]
            if not job or not parti:
                return ""
            return " ".join(
                parte if indice == 0 and not parte.startswith(("/", "-")) else f"{job}{parte}"
                for indice, parte in enumerate(parti)
            )
        if tipo == self.TipoRiferimento.CAMPO_PIANO:
            attributo = self._CAMPI_PIANO.get(valore)
            return str(getattr(piano, attributo, "") or "").strip() if attributo else ""
        return ""


class PuntoIntervento(models.TextChoices):
    """Cosa fa un ente di ispezione su uno step del piano."""

    WITNESS = "W", "Witness point"
    HOLD = "H", "Hold point"
    REVIEW = "R", "Review"
    SPOT_WITNESS = "SW", "Spot witness"
    MONITORING = "M", "Monitoring"
    APPROVAL = "A", "Approval"
    FIRST_OF_A_KIND = "F", "First of a kind"
    VEDI_FOGLIO = "(*)", "See dedicated sheet"
    NON_COINVOLTO = "-", "Not involved"


class QualityControlPlanSection(models.Model):
    """Sezione del corpo di un piano: una fase costruttiva dell'apparecchio.

    Il titolo è libero ("Documents approval", "Shell closure seams after
    PWHT"…) perché dipende dall'apparecchio; l'ordine è la sequenza delle fasi.
    """

    piano = models.ForeignKey(
        QualityControlPlan,
        db_column="IdQCP",
        on_delete=models.CASCADE,
        related_name="sections",
    )
    titolo = models.CharField(db_column="Titolo", max_length=200, verbose_name="Titolo")
    ordine = models.PositiveSmallIntegerField(db_column="Ordine", default=0)

    class Meta:
        managed = True
        db_table = "quality_control_plan_sections"
        verbose_name = "Sezione del Quality Control Plan"
        verbose_name_plural = "Sezioni del Quality Control Plan"
        ordering = ["ordine", "id"]

    def __str__(self):
        return self.titolo


class QualityControlPlanStep(models.Model):
    """Step di una sezione: un controllo previsto sull'apparecchio.

    Lo step copia i valori dall'attività di catalogo invece di leggerli via
    relazione (snapshot), per due ragioni: il catalogo cambia nel tempo e un
    piano già emesso non deve cambiare con lui; e l'utente deve poter correggere
    un singolo step senza toccare l'anagrafica, che vale per tutte le commesse.
    ``attivita`` resta solo come traccia dell'origine: è vuota per gli step
    scritti a mano, e PROTECT impedisce di cancellare un'attività ancora usata.

    La numerazione progressiva degli step non è una colonna: si calcola in
    lettura (``serialize_corpo``), come la formula dell'Excel, così resta giusta
    dopo ogni inserimento, spostamento o cancellazione.
    """

    sezione = models.ForeignKey(
        QualityControlPlanSection,
        db_column="IdSezione",
        on_delete=models.CASCADE,
        related_name="steps",
    )
    attivita = models.ForeignKey(
        AttivitaQCP,
        db_column="IdAttivita",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="steps",
        verbose_name="Attività di catalogo",
    )
    ordine = models.PositiveSmallIntegerField(db_column="Ordine", default=0)

    # Snapshot dei valori al momento dell'inserimento
    descrizione = models.CharField(
        db_column="Descrizione", max_length=300, verbose_name="Descrizione"
    )
    test_inspection = models.CharField(
        db_column="TestInspection", max_length=200, blank=True, verbose_name="Test / inspection"
    )
    reference_doc = models.CharField(
        db_column="ReferenceDoc", max_length=200, blank=True, verbose_name="Reference doc."
    )
    acceptance_criteria = models.CharField(
        db_column="AcceptanceCriteria",
        max_length=300,
        blank=True,
        verbose_name="Acceptance criteria",
    )
    documento_richiesto = models.CharField(
        db_column="DocumentoRichiesto",
        max_length=200,
        blank=True,
        verbose_name="Documento richiesto",
    )
    tecnica = models.CharField(
        db_column="Tecnica", max_length=50, blank=True, verbose_name="Tecnica"
    )
    report_no = models.CharField(
        db_column="ReportNo", max_length=100, blank=True, verbose_name="Report n."
    )

    # Compilati dall'utente
    extent = models.DecimalField(
        db_column="Extent",
        max_digits=4,
        decimal_places=3,
        default=1,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        verbose_name="Extent",
        help_text="Frazione fra 0 e 1: 0.1 vuol dire 10%.",
    )
    remarks = models.CharField(
        db_column="Remarks", max_length=300, blank=True, verbose_name="Remarks"
    )

    class Meta:
        managed = True
        db_table = "quality_control_plan_steps"
        verbose_name = "Step del Quality Control Plan"
        verbose_name_plural = "Step del Quality Control Plan"
        ordering = ["ordine", "id"]

    def __str__(self):
        return self.descrizione


class QualityControlPlanInterventionPoint(models.Model):
    """Punto d'intervento di un ente di ispezione su uno step.

    Ogni step ha un punto per ogni ente del piano ("-" se l'ente non è
    coinvolto), così l'interfaccia può contare su una riga per ente. Gli enti
    sono quelli della copertina e il loro ordine è l'ordine delle colonne.
    """

    step = models.ForeignKey(
        QualityControlPlanStep,
        db_column="IdStep",
        on_delete=models.CASCADE,
        related_name="punti",
    )
    agency = models.ForeignKey(
        QualityControlPlanAgency,
        db_column="IdEnte",
        on_delete=models.CASCADE,
        related_name="punti",
        verbose_name="Ente",
    )
    # Uno o più stati di PuntoIntervento separati da "/" ("R/SW": review e spot
    # witness insieme), oppure "-". Non sono ``choices`` perché le combinazioni
    # non sono un elenco chiuso: le controlla ``normalizza_punto`` nel service, e
    # anche tutti gli stati insieme stanno in questa lunghezza.
    punto = models.CharField(
        db_column="Punto",
        max_length=20,
        default=PuntoIntervento.NON_COINVOLTO,
        verbose_name="Punto d'intervento",
    )

    class Meta:
        managed = True
        db_table = "quality_control_plan_intervention_points"
        verbose_name = "Punto d'intervento"
        verbose_name_plural = "Punti d'intervento"
        ordering = ["agency__ordine", "agency_id"]
        constraints = [
            models.UniqueConstraint(fields=["step", "agency"], name="uniq_qcp_punto_step_ente"),
        ]

    def __str__(self):
        return f"{self.agency_id}: {self.punto}"


class EsitoFirma(models.TextChoices):
    """Cosa dichiara chi firma un punto d'intervento."""

    # Etichette in inglese, come la pagina del piano e il documento QCP.
    CONFORME = "conforme", "Conforming"
    NON_CONFORME = "non_conforme", "Non-conforming"
    NON_APPLICABILE = "non_applicabile", "Not applicable"


class FirmaNonModificabile(ValueError):
    """Una firma registrata non si cambia e non si cancella: si annulla."""


class _FirmeQuerySet(models.QuerySet):
    def delete(self):
        raise FirmaNonModificabile("Le firme non si cancellano: si annullano, col motivo.")


class QualityControlPlanSignature(models.Model):
    """Firma di esecuzione di un punto d'intervento: chi, con quale esito, quando.

    Prende il posto della colonna "Sign" dell'Excel, firmata a penna in officina
    sul cartaceo. È una firma elettronica semplice: l'utente autenticato
    dichiara che il controllo è avvenuto, e il sistema registra chi, cosa e
    quando. Non è una firma digitale e non ne ha il valore legale.

    Si aggancia al punto d'intervento, non allo step: lo stesso step può
    richiedere l'intervento di più enti, e ciascuno è un evento distinto.

    APPEND-ONLY. Una firma non si modifica e non si cancella: esito e note
    restano quelli registrati. Un errore si corregge annullando la firma (data,
    autore e motivo dell'annullamento sulla stessa riga) e, se serve, firmando
    di nuovo; lo storico del punto resta intero. Per questo ``delete()`` è
    vietato, sull'oggetto e sui queryset, ``save()`` su una firma esistente
    accetta solo i campi dell'annullamento, e PROTECT impedisce di cancellare
    punti, step, sezioni o piani che hanno firme.

    Una firma è valida finché ``annullata_il`` è vuoto, e un punto ne ha al
    massimo una valida. Lo garantisce il database (``uniq_qcp_firma_valida``),
    non solo il service: due clic ravvicinati non producono due firme.

    TODO(firme esterne): oggi firma solo l'utente interno autenticato. Cliente
    e Authorized Inspector firmano ancora sul cartaceo, finché non sarà chiaro
    come condividere il piano con soggetti esterni e se i rispettivi organismi
    accettano una firma elettronica. La struttura (una firma per punto, cioè
    per ente) regge già quel caso: non c'è altro da preparare in anticipo.

    TODO(istantanea dell'immagine): la firma non conserva una copia del PNG, ma
    mostra l'immagine attuale dell'utente (``User.firma``). Se servirà che resti
    immutabile anche quando l'utente la cambia, andrà salvata un'istantanea del
    file al momento della firma.
    """

    punto = models.ForeignKey(
        QualityControlPlanInterventionPoint,
        db_column="IdPunto",
        on_delete=models.PROTECT,
        related_name="firme",
        verbose_name="Punto d'intervento",
    )
    utente = models.ForeignKey(
        User,
        db_column="IdUtente",
        on_delete=models.PROTECT,
        related_name="firme_qcp",
        verbose_name="Firmata da",
    )
    firmato_il = models.DateTimeField(db_column="FirmatoIl", auto_now_add=True)
    esito = models.CharField(db_column="Esito", max_length=20, choices=EsitoFirma.choices)
    note = models.TextField(db_column="Note", blank=True)

    annullata_il = models.DateTimeField(db_column="AnnullataIl", null=True, blank=True)
    annullata_da = models.ForeignKey(
        User,
        db_column="AnnullataDa",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="firme_qcp_annullate",
        verbose_name="Annullata da",
    )
    motivo_annullo = models.TextField(db_column="MotivoAnnullo", blank=True)

    objects = _FirmeQuerySet.as_manager()

    # Gli unici campi che si scrivono su una firma già registrata.
    CAMPI_ANNULLO = frozenset({"annullata_il", "annullata_da", "motivo_annullo"})

    class Meta:
        managed = True
        db_table = "quality_control_plan_signatures"
        verbose_name = "Firma del Quality Control Plan"
        verbose_name_plural = "Firme del Quality Control Plan"
        ordering = ["firmato_il", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["punto"],
                condition=Q(annullata_il__isnull=True),
                name="uniq_qcp_firma_valida",
            ),
        ]

    def __str__(self):
        stato = "valida" if self.valida else "annullata"
        return f"Punto {self.punto_id}: {self.get_esito_display()} ({stato})"

    @property
    def valida(self):
        return self.annullata_il is None

    def save(self, *args, **kwargs):
        if not self._state.adding:
            campi = set(kwargs.get("update_fields") or ())
            if not campi or not campi <= self.CAMPI_ANNULLO:
                raise FirmaNonModificabile(
                    "Una firma registrata non si modifica: si può solo annullare."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise FirmaNonModificabile("Le firme non si cancellano: si annullano, col motivo.")
