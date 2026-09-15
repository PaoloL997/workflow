from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Stabilimento(models.Model):
    nome = models.CharField(db_column="Nome", max_length=100, unique=True)
    # Null perché non tutti gli stabilimenti sono siti costruttivi: solo quelli
    # che lo sono hanno una sigla e un codice sito su Business Central.
    sigla = models.CharField(db_column="Sigla", max_length=2, unique=True, null=True, blank=True)
    codice_bc = models.PositiveSmallIntegerField(
        db_column="CodiceBC",
        unique=True,
        null=True,
        blank=True,
        verbose_name="Codice sito Business Central",
    )

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


class TipoIndirizzoStabilimento(models.TextChoices):
    TO = "to", "A"
    CC = "cc", "CC"


class IndirizzoStabilimento(models.Model):
    """Indirizzo email di uno stabilimento, per il trasmittal interno."""

    stabilimento = models.ForeignKey(
        Stabilimento,
        on_delete=models.CASCADE,
        related_name="indirizzi",
    )
    email = models.EmailField()
    tipo = models.CharField(max_length=10, choices=TipoIndirizzoStabilimento.choices)
    attivo = models.BooleanField(default=True)

    class Meta:
        managed = True
        db_table = "indirizzi_stabilimento"
        verbose_name = "Indirizzo stabilimento"
        verbose_name_plural = "Indirizzi stabilimento"
        ordering = ["stabilimento", "tipo", "email"]
        constraints = [
            models.UniqueConstraint(
                fields=["stabilimento", "email", "tipo"],
                name="uniq_indirizzo_stabilimento",
            ),
        ]

    def __str__(self):
        return f"{self.stabilimento_id}: {self.email} ({self.tipo})"


class RuoloFirmatarioStabilimento(models.TextChoices):
    PRODUZIONE = "produzione", "Produzione"
    QUALITA = "qualita", "Qualità"


class FirmatarioStabilimento(models.Model):
    """Chi firma per uno stabilimento nel trasmittal interno, per ruolo.

    L'immagine della firma è quella dell'utente (``User.firma``), non un
    campo di questo modello. Lo stesso utente può firmare per più
    stabilimenti: è voluto.
    """

    stabilimento = models.ForeignKey(
        Stabilimento,
        on_delete=models.CASCADE,
        related_name="firmatari",
    )
    ruolo = models.CharField(max_length=20, choices=RuoloFirmatarioStabilimento.choices)
    utente = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="firmatario_di",
    )

    class Meta:
        managed = True
        db_table = "firmatari_stabilimento"
        verbose_name = "Firmatario stabilimento"
        verbose_name_plural = "Firmatari stabilimento"
        ordering = ["stabilimento", "ruolo"]
        constraints = [
            models.UniqueConstraint(
                fields=["stabilimento", "ruolo"],
                name="uniq_firmatario_stabilimento_ruolo",
            ),
        ]

    def __str__(self):
        return f"{self.stabilimento_id}: {self.ruolo} = {self.utente_id}"


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
    # Non sincronizzato automaticamente da Business Central (NBT_BRL Location
    # Code, vedi src.erp.business_central.get_commessa_codice_sito): impostato
    # a mano finché non esiste una sync dedicata. Prerequisito per il
    # trasmittal interno, che deve sapere dove viene costruita la commessa.
    sito_costruttivo = models.ForeignKey(
        Stabilimento,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="commesse_costruttive",
        verbose_name="Sito costruttivo",
    )

    class Meta:
        managed = True
        db_table = "testate"
        verbose_name = "Archivio commessa"
        verbose_name_plural = "Archivi commessa"

    def clean(self):
        super().clean()
        if self.sito_costruttivo_id and self.sito_costruttivo.codice_bc is None:
            raise ValidationError(
                {
                    "sito_costruttivo": (
                        "Lo stabilimento selezionato non ha un codice sito: non può "
                        "essere il sito costruttivo di una commessa."
                    )
                }
            )

    def __str__(self):
        return self.job


class RuoloPersonaCommessa(models.TextChoices):
    PM = "pm", "PM"
    PE = "pe", "PE"
    QCI = "qci", "QCI"
    WE = "we", "WE"


class PersonaCommessa(models.Model):
    """Una persona assegnata a un ruolo (PM/PE/QCI/WE) di una commessa.

    La persona è un utente registrato (``utente``) oppure, se non censito
    nell'app, un nome libero (``nome_libero``): mai entrambi, mai nessuno dei
    due. Più persone possono coprire lo stesso ruolo sulla stessa commessa.
    """

    testata = models.ForeignKey(Testata, on_delete=models.CASCADE, related_name="persone")
    ruolo = models.CharField(max_length=10, choices=RuoloPersonaCommessa.choices)
    utente = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="commesse_persona",
    )
    nome_libero = models.CharField(max_length=200, blank=True)

    class Meta:
        managed = True
        db_table = "persone_commessa"
        verbose_name = "Persona commessa"
        verbose_name_plural = "Persone commessa"
        ordering = ["testata", "ruolo", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(utente__isnull=False, nome_libero="")
                    | (models.Q(utente__isnull=True) & ~models.Q(nome_libero=""))
                ),
                name="ck_persona_commessa_utente_xor_nome_libero",
            ),
        ]

    def __str__(self):
        return f"{self.testata_id}: {self.ruolo} = {self.nome_visualizzato}"

    @property
    def nome_visualizzato(self):
        """Nome e cognome se collegata a un utente, altrimenti il testo libero.

        Mostra sempre "Nome Cognome" (non lo username): cade sullo username
        solo nel raro caso in cui l'utente non abbia né nome né cognome
        compilati.
        """
        if not self.utente_id:
            return self.nome_libero
        nome_cognome = f"{self.utente.first_name} {self.utente.last_name}".strip()
        return nome_cognome or self.utente.nome_completo


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


class DestinazioneDocumento(models.Model):
    """Stabilimenti che devono ricevere copia cartacea di un documento.

    Sostituisce il bitmask a 5 cifre del vecchio ``<job>-RecipientsData.txt``
    (strumento Excel): il dato è persistente e indipendente dalla singola
    lettera del trasmittal interno, si imposta una volta per documento e vale
    per tutte le trasmissioni successive.
    """

    documento = models.ForeignKey(
        Documento,
        on_delete=models.CASCADE,
        related_name="destinazioni",
    )
    stabilimento = models.ForeignKey(
        Stabilimento,
        on_delete=models.PROTECT,
        related_name="documenti_destinati",
    )

    class Meta:
        managed = True
        db_table = "destinazioni_documento"
        verbose_name = "Destinazione documento"
        verbose_name_plural = "Destinazioni documento"
        ordering = ["documento", "stabilimento"]
        constraints = [
            models.UniqueConstraint(
                fields=["documento", "stabilimento"],
                name="uniq_destinazione_documento",
            ),
        ]

    def clean(self):
        super().clean()
        if self.stabilimento_id and self.stabilimento.codice_bc is None:
            raise ValidationError(
                {
                    "stabilimento": (
                        "Lo stabilimento non ha un codice sito: non può essere una "
                        "destinazione documento."
                    )
                }
            )

    def __str__(self):
        return f"{self.documento_id}: {self.stabilimento_id}"


class TransmittalInterno(models.Model):
    """Lettera di trasmittal interno (form MQ 7.5-04), archiviata dopo l'emissione.

    Il progressivo riparte da 1 ogni giorno, per commessa (vedi
    ``core.services.trasmittal_interno.prossimo_progressivo``); ``nome`` è il
    nome leggibile che ne deriva (``<job>_<yyyy-mm-dd>_E<n>``).
    """

    testata = models.ForeignKey(
        Testata,
        on_delete=models.PROTECT,
        related_name="trasmittal_interni",
    )
    data = models.DateField()
    progressivo = models.PositiveSmallIntegerField()
    nome = models.CharField(max_length=100, unique=True)
    creato_da = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="trasmittal_interni_creati",
    )
    creato_il = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    class Meta:
        managed = True
        db_table = "trasmittal_interni"
        verbose_name = "Trasmittal interno"
        verbose_name_plural = "Trasmittal interni"
        ordering = ["-data", "-progressivo"]
        constraints = [
            models.UniqueConstraint(
                fields=["testata", "data", "progressivo"],
                name="uniq_trasmittal_interno_progressivo",
            ),
        ]

    def __str__(self):
        return self.nome


class RigaTransmittalInterno(models.Model):
    """Un documento incluso in un trasmittal interno, con la sua riga stampata.

    ``siti`` è uno SNAPSHOT dei siti coinvolti al momento dell'emissione: non
    una lettura live di ``DestinazioneDocumento``, che nel frattempo può
    cambiare senza toccare le lettere già emesse.
    """

    trasmittal = models.ForeignKey(
        TransmittalInterno,
        on_delete=models.CASCADE,
        related_name="righe",
    )
    documento = models.ForeignKey(
        Documento,
        on_delete=models.PROTECT,
        related_name="righe_trasmittal_interno",
    )
    revisione = models.CharField(max_length=10)
    copie = models.PositiveSmallIntegerField(null=True, blank=True)
    tpi = models.CharField(max_length=50, blank=True)
    note = models.CharField(max_length=300, blank=True)
    cliente = models.BooleanField(default=True)
    siti = models.ManyToManyField(
        Stabilimento,
        blank=True,
        related_name="righe_trasmittal_interno",
        db_table="riga_trasmittal_interno_siti",
    )
    posizione = models.PositiveSmallIntegerField(help_text="Ordine di stampa nella lettera.")

    class Meta:
        managed = True
        db_table = "righe_trasmittal_interno"
        verbose_name = "Riga trasmittal interno"
        verbose_name_plural = "Righe trasmittal interno"
        ordering = ["trasmittal", "posizione"]
        constraints = [
            models.UniqueConstraint(
                fields=["trasmittal", "documento"],
                name="uniq_riga_trasmittal_interno_documento",
            ),
        ]

    def __str__(self):
        return f"{self.trasmittal_id}: {self.documento_id}"


class TipoDestinatarioTransmittalInterno(models.TextChoices):
    TO = "to", "A"
    CC = "cc", "CC"


class OrigineDestinatarioTransmittalInterno(models.TextChoices):
    STABILIMENTO = "stabilimento", "Stabilimento"
    PM = "pm", "PM"
    PE = "pe", "PE"
    QCI = "qci", "QCI"
    EXPORT = "export", "Export"


class DestinatarioTransmittalInterno(models.Model):
    """Un destinatario email di un trasmittal interno, con la sua origine.

    ``origine`` spiega perché quell'indirizzo è finito in lista: vedi
    ``core.services.trasmittal_interno.crea_trasmittal_interno`` per le
    regole di indirizzamento (stabilimento, PM, PE, QCI, export@ per i
    documenti SHn). WE non ha un'origine dedicata: la sua lista di
    distribuzione non è ancora definita.
    """

    trasmittal = models.ForeignKey(
        TransmittalInterno,
        on_delete=models.CASCADE,
        related_name="destinatari",
    )
    email = models.EmailField()
    tipo = models.CharField(max_length=10, choices=TipoDestinatarioTransmittalInterno.choices)
    origine = models.CharField(max_length=20, choices=OrigineDestinatarioTransmittalInterno.choices)

    class Meta:
        managed = True
        db_table = "destinatari_trasmittal_interno"
        verbose_name = "Destinatario trasmittal interno"
        verbose_name_plural = "Destinatari trasmittal interno"
        ordering = ["trasmittal", "tipo", "email"]
        constraints = [
            models.UniqueConstraint(
                fields=["trasmittal", "email"],
                name="uniq_destinatario_trasmittal_interno",
            ),
        ]

    def __str__(self):
        return f"{self.trasmittal_id}: {self.email} ({self.tipo})"


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
