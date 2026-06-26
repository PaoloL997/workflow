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
        self.is_staff = self.permesso == Permesso.ADMIN
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

    class Meta:
        managed = True
        db_table = "revisioni"
        verbose_name = "Revisione"
        verbose_name_plural = "Revisioni"
        ordering = ["rev_no"]

    def __str__(self):
        label = f"Rev {self.rev_no}" if self.rev_no is not None else f"Rev #{self.pk}"
        if self.rev_let:
            label += self.rev_let
        return label


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
