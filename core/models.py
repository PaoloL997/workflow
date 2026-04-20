from django.db import models
from django.contrib.auth.models import AbstractUser


class Reparto(models.Model):
    nome = models.CharField(db_column='Nome', max_length=100, unique=True)

    class Meta:
        managed = True
        db_table = 'reparti'
        verbose_name = 'Reparto'
        verbose_name_plural = 'Reparti'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class User(AbstractUser):
    email = models.EmailField(db_column='Email', unique=True)
    ruolo = models.CharField(db_column='Ruolo', max_length=100, blank=True)
    reparto = models.CharField(db_column='Reparto', max_length=100, blank=True)

    class Meta:
        managed = True
        db_table = 'users'
        verbose_name = 'Utente'
        verbose_name_plural = 'Utenti'

    def __str__(self):
        return self.username


class Testata(models.Model):
    job = models.CharField(db_column='Job', max_length=50, unique=True)
    vb_job = models.CharField(db_column='VBJob', max_length=50, blank=True)
    client = models.CharField(db_column='Client', max_length=200, blank=True)
    po_no = models.CharField(db_column='PONo', max_length=100, blank=True)
    job_detail = models.CharField(db_column='JobDetail', max_length=300, blank=True)
    delivery_date = models.DateField(db_column='DeliveryDate', blank=True, null=True)
    delivery_term = models.CharField(db_column='DeliveryTerm', max_length=200, blank=True)
    requisition = models.CharField(db_column='Requisition', max_length=100, blank=True)
    time_cli_doc_rev = models.IntegerField(
        db_column='TimeCliDocRev', blank=True, null=True,
        help_text='Giorni a disposizione del cliente per revisionare un documento.',
    )
    time_ven_doc_rev = models.IntegerField(
        db_column='TimeVenDocRev', blank=True, null=True,
        help_text='Giorni a nostra disposizione per emettere/revisionare un documento.',
    )
    rev_let_flag = models.BooleanField(db_column='RevLetFlag', default=False)
    transm_flag = models.BooleanField(db_column='TransmFlag', default=False)

    class Meta:
        managed = True
        db_table = 'testate'
        verbose_name = 'Archivio commessa'
        verbose_name_plural = 'Archivi commessa'

    def __str__(self):
        return self.job


class IndirSped(models.Model):
    testata = models.ForeignKey(
        Testata, to_field='job',
        db_column='Job', on_delete=models.CASCADE,
        related_name='indirizzi_spedizione',
    )
    consignee = models.CharField(db_column='Consignee', max_length=200, blank=True)
    address = models.CharField(db_column='Address', max_length=300, blank=True)
    zip_code = models.CharField(db_column='ZipCode', max_length=20, blank=True)
    city = models.CharField(db_column='City', max_length=100, blank=True)
    country = models.CharField(db_column='Country', max_length=100, blank=True)
    attn = models.CharField(db_column='Attn', max_length=200, blank=True)
    ph_no = models.CharField(db_column='PhNo', max_length=50, blank=True)

    class Meta:
        managed = True
        db_table = 'indirizzi_spedizione'
        verbose_name = 'Indirizzo di spedizione'
        verbose_name_plural = 'Indirizzi di spedizione'

    def __str__(self):
        parts = [self.consignee, self.city, self.country]
        return ' — '.join(p for p in parts if p) or f'Indirizzo #{self.pk}'


# ── Choices for Revisione.int_status (hardcoded, replaces StatoInterno model) ─
STATI_INTERNI_CHOICES = [
    ('da_iniziare', 'Da iniziare'),
    ('in_lavorazione', 'In lavorazione'),
    ('in_revisione', 'In revisione'),
    ('in_approvazione', 'In approvazione'),
    ('da_emettere', 'Da emettere'),
    ('inviato_al_cliente', 'Inviato al Cliente'),
    ('ricevuto', 'Ricevuto'),
]

# ── Choices for Ticket.stato ─────────────────────────────────────────────────
STATO_TICKET_CHOICES = [
    ('da_iniziare', 'Da iniziare'),
    ('in_lavorazione', 'In lavorazione'),
    ('in_revisione', 'In revisione'),
    ('in_approvazione', 'In approvazione'),
    ('concluso', 'Concluso'),
]


class StatoEsterno(models.Model):
    nome = models.CharField(db_column='Nome', max_length=100, unique=True)
    colore = models.CharField(db_column='Colore', max_length=7, blank=True, default='',
                              help_text='Colore esadecimale (es. #00B050).')

    class Meta:
        managed = True
        db_table = 'stati_esterni'
        verbose_name = 'Stato esterno'
        verbose_name_plural = 'Stati esterni'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Documento(models.Model):
    testata = models.ForeignKey(
        Testata, to_field='job',
        db_column='Job', on_delete=models.CASCADE,
        related_name='documenti',
    )
    item_no = models.CharField(db_column='ItemNo', max_length=100, blank=True)
    vendor_doc = models.CharField(db_column='VendorDoc', max_length=200, blank=True)
    client_doc_no = models.CharField(db_column='ClientDocNo', max_length=200, blank=True)
    client_doc_class = models.CharField(db_column='ClientDocClass', max_length=200, blank=True)
    doc_title = models.CharField(db_column='DocTitle', max_length=300, blank=True)
    doc_penalty = models.BooleanField(db_column='DocPenalty', default=False)
    doc_payment = models.BooleanField(db_column='DocPayment', default=False)
    rev_gen = models.BooleanField(db_column='RevGen', default=False)
    reparto = models.CharField(
        db_column='Reparto', max_length=100, blank=True, default='',
        help_text='Nome del reparto responsabile.',
    )
    remarks = models.TextField(db_column='Remarks', blank=True)

    class Meta:
        managed = True
        db_table = 'documenti'
        verbose_name = 'Documento'
        verbose_name_plural = 'Documenti'

    def __str__(self):
        return f'{self.testata_id} — {self.doc_title or self.pk}'


class Revisione(models.Model):
    documento = models.ForeignKey(
        Documento, db_column='IdDoc', on_delete=models.CASCADE,
        related_name='revisioni',
    )
    rev_no = models.IntegerField(db_column='RevNo', blank=True, null=True)
    rev_let = models.CharField(db_column='RevLet', max_length=10, blank=True)
    dis_plan_date = models.DateField(db_column='DisPlanDate', blank=True, null=True)
    dis_act_date = models.DateField(db_column='DisActDate', blank=True, null=True)
    rec_plan_date = models.DateField(db_column='RecPlanDate', blank=True, null=True)
    rec_act_date = models.DateField(db_column='RecActDate', blank=True, null=True)
    int_status = models.CharField(
        db_column='IntStatus', max_length=50, blank=True, default='',
        choices=STATI_INTERNI_CHOICES,
    )
    ext_status = models.ForeignKey(
        StatoEsterno, db_column='ExtStatus', on_delete=models.SET_NULL,
        blank=True, null=True, related_name='revisioni',
    )
    crea_nuova_rev = models.BooleanField(
        db_column='CreaNuovaRev', default=False,
        help_text='Flag per creare una nuova revisione al rientro dal cliente.',
    )
    note_rientro = models.TextField(
        db_column='NoteRientro', blank=True, default='',
        help_text='Note relative al rientro dal cliente.',
    )

    class Meta:
        managed = True
        db_table = 'revisioni'
        verbose_name = 'Revisione'
        verbose_name_plural = 'Revisioni'
        ordering = ['rev_no']

    def __str__(self):
        label = f'Rev {self.rev_no}' if self.rev_no is not None else f'Rev #{self.pk}'
        if self.rev_let:
            label += self.rev_let
        return label


class Ticket(models.Model):
    reparto = models.CharField(db_column='Reparto', max_length=100)
    commessa = models.CharField(
        db_column='Commessa', max_length=50, blank=True, default='',
        help_text='Numero commessa derivato dalle revisioni collegate.',
    )
    progressivo = models.PositiveIntegerField(
        db_column='Progressivo', default=0,
        help_text='Progressivo per commessa (auto-generato).',
    )
    esecutore = models.ForeignKey(
        User, db_column='Esecutore', on_delete=models.RESTRICT,
        related_name='ticket_esecutore',
    )
    revisore = models.ForeignKey(
        User, db_column='Revisore', on_delete=models.RESTRICT,
        related_name='ticket_revisore',
    )
    approvatore = models.ForeignKey(
        User, db_column='Approvatore', on_delete=models.RESTRICT,
        related_name='ticket_approvatore',
    )
    stato = models.CharField(
        db_column='Stato', max_length=50,
        choices=STATO_TICKET_CHOICES, default='da_iniziare',
    )
    revisioni = models.ManyToManyField(
        Revisione, related_name='tickets', blank=True,
        db_table='ticket_revisioni',
    )
    created_at = models.DateTimeField(db_column='CreatedAt', auto_now_add=True)
    updated_at = models.DateTimeField(db_column='UpdatedAt', auto_now=True)

    class Meta:
        managed = True
        db_table = 'ticket'
        verbose_name = 'Ticket'
        verbose_name_plural = 'Ticket'
        ordering = ['-created_at']

    @property
    def nome(self):
        if self.commessa and self.progressivo:
            return f'{self.commessa}-{self.progressivo}'
        return f'#{self.pk}'

    def __str__(self):
        return f'{self.nome} — {self.reparto}'


class TicketNota(models.Model):
    ticket = models.ForeignKey(
        Ticket, db_column='TicketId', on_delete=models.CASCADE,
        related_name='note',
    )
    autore = models.ForeignKey(
        User, db_column='Autore', on_delete=models.SET_NULL,
        null=True, related_name='note_ticket',
    )
    testo = models.TextField(db_column='Testo')
    created_at = models.DateTimeField(db_column='CreatedAt', auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'ticket_note'
        verbose_name = 'Nota ticket'
        verbose_name_plural = 'Note ticket'
        ordering = ['created_at']

    def __str__(self):
        return f'Nota #{self.pk} su Ticket #{self.ticket_id}'


class Notifica(models.Model):
    destinatario = models.ForeignKey(
        User, db_column='Destinatario', on_delete=models.CASCADE,
        related_name='notifiche',
    )
    testo = models.CharField(db_column='Testo', max_length=500)
    ticket = models.ForeignKey(
        Ticket, db_column='TicketId', on_delete=models.CASCADE,
        null=True, blank=True, related_name='notifiche',
    )
    letta = models.BooleanField(db_column='Letta', default=False)
    created_at = models.DateTimeField(db_column='CreatedAt', auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'notifiche'
        verbose_name = 'Notifica'
        verbose_name_plural = 'Notifiche'
        ordering = ['-created_at']

    def __str__(self):
        return f'Notifica per {self.destinatario} — {self.testo[:50]}'

