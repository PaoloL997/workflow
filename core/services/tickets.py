"""
Business logic for Ticket, TicketNota, and Notifica management.
Includes CRUD operations and workflow state transitions per Revisione.
"""

from collections import Counter
from django.db import transaction
from django.db.models import Q

from ..models import (
    Ticket, TicketNota, Notifica, Revisione, User,
    STATI_INTERNI_CHOICES, STATI_ATTIVI_REV, STATI_CONCLUSI_REV,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _ticket_is_concluso(ticket):
    """A ticket is concluso when ALL its revisioni have left the workflow."""
    statuses = list(ticket.revisioni.values_list('int_status', flat=True))
    if not statuses:
        return False
    return all(s in STATI_CONCLUSI_REV for s in statuses)


def _ticket_status_counts(ticket):
    counts = Counter(ticket.revisioni.values_list('int_status', flat=True))
    return {k or '': v for k, v in counts.items()}


# ── Serializers ──────────────────────────────────────────────────────────────

def serialize_ticket(t):
    from ..models import Testata
    testata = None
    if t.commessa:
        testata = Testata.objects.filter(job=t.commessa).first()

    revisioni = list(t.revisioni.select_related('documento__testata', 'ext_status'))

    # Earliest planned dispatch date across linked revisions
    dates = [r.dis_plan_date for r in revisioni if r.dis_plan_date is not None]
    data_prevista_invio = min(dates).strftime('%d/%m/%Y') if dates else ''

    statuses = [r.int_status or '' for r in revisioni]
    counts = Counter(statuses)
    is_concluso = bool(statuses) and all(s in STATI_CONCLUSI_REV for s in statuses)

    return {
        'id': t.pk,
        'nome': t.nome,
        'commessa': t.commessa,
        'progressivo': t.progressivo,
        'reparto': t.reparto,
        'esecutore': {'id': t.esecutore_id, 'username': t.esecutore.username, 'nome_completo': t.esecutore.nome_completo},
        'revisore':  {'id': t.revisore_id,  'username': t.revisore.username,  'nome_completo': t.revisore.nome_completo},
        'approvatore': {'id': t.approvatore_id, 'username': t.approvatore.username, 'nome_completo': t.approvatore.nome_completo},
        'is_concluso': is_concluso,
        'status_counts': dict(counts),
        'revisioni': [_serialize_ticket_revisione(r) for r in revisioni],
        'created_at': t.created_at.isoformat() if t.created_at else None,
        'updated_at': t.updated_at.isoformat() if t.updated_at else None,
        'cliente': testata.client if testata else '',
        'descrizione_commessa': testata.job_detail if testata else '',
        'data_prevista_invio': data_prevista_invio,
    }


def _serialize_ticket_revisione(r):
    label_map = dict(STATI_INTERNI_CHOICES)
    return {
        'id': r.pk,
        'documento_id': r.documento_id,
        'job': r.documento.testata_id,
        'doc_title': r.documento.doc_title,
        'vendor_doc': r.documento.vendor_doc,
        'rev_no': r.rev_no,
        'dis_plan_date': r.dis_plan_date.strftime('%d/%m/%Y') if r.dis_plan_date else '',
        'dis_plan_date_iso': r.dis_plan_date.isoformat() if r.dis_plan_date else '',
        'int_status': r.int_status,
        'int_status_label': label_map.get(r.int_status, r.int_status),
        'ext_status_label': r.ext_status.nome if r.ext_status else '',
        'reparto_nome': r.documento.reparto or '',
    }


def serialize_nota(n):
    return {
        'id': n.pk,
        'ticket_id': n.ticket_id,
        'autore': n.autore.nome_completo if n.autore else None,
        'testo': n.testo,
        'created_at': n.created_at.isoformat() if n.created_at else None,
    }


def serialize_notifica(n):
    return {
        'id': n.pk,
        'testo': n.testo,
        'ticket_id': n.ticket_id,
        'letta': n.letta,
        'created_at': n.created_at.isoformat() if n.created_at else None,
    }


# ── Ticket CRUD ──────────────────────────────────────────────────────────────

def list_tickets(reparto=None, concluso=None, commessa=None):
    """
    concluso: None (all), True (only finished), False (only active).
    A ticket is "concluso" when all its revisioni are in STATI_CONCLUSI_REV.
    """
    qs = Ticket.objects.select_related('esecutore', 'revisore', 'approvatore').prefetch_related('revisioni')
    if reparto:
        qs = qs.filter(reparto=reparto)
    if commessa:
        qs = qs.filter(
            revisioni__documento__testata__job__icontains=commessa
        ).distinct()

    tickets = list(qs)
    if concluso is True:
        tickets = [t for t in tickets if _ticket_is_concluso(t)]
    elif concluso is False:
        tickets = [t for t in tickets if not _ticket_is_concluso(t)]
    return [serialize_ticket(t) for t in tickets]


def get_ticket(pk):
    return Ticket.objects.select_related(
        'esecutore', 'revisore', 'approvatore'
    ).get(pk=pk)


@transaction.atomic
def create_ticket(data, user):
    """Create a ticket and link revisions. Auto-generates nome as {commessa}-{progressivo}."""
    revisione_ids = data.get('revisione_ids', [])

    # Derive commessa from the linked revisions (all should belong to the same commessa)
    commessa = ''
    if revisione_ids:
        jobs = list(
            Revisione.objects.filter(id__in=revisione_ids)
            .values_list('documento__testata__job', flat=True)
            .distinct()
        )
        if jobs:
            commessa = jobs[0]

    progressivo = 1
    if commessa:
        last = Ticket.objects.filter(commessa=commessa).order_by('-progressivo').first()
        if last and last.progressivo:
            progressivo = last.progressivo + 1

    t = Ticket(
        reparto=data.get('reparto') or '',
        commessa=commessa,
        progressivo=progressivo,
        esecutore_id=data['esecutore_id'],
        revisore_id=data['revisore_id'],
        approvatore_id=data['approvatore_id'],
    )
    t.full_clean()
    t.save()

    if revisione_ids:
        t.revisioni.set(revisione_ids)
        # Bring linked revisions into the workflow.
        Revisione.objects.filter(id__in=revisione_ids).update(int_status='da_iniziare')

    destinatari = {t.esecutore_id, t.revisore_id, t.approvatore_id}
    for uid in destinatari:
        Notifica.objects.create(
            destinatario_id=uid,
            testo=f'Sei stato assegnato al Ticket {t.nome} ({t.reparto})',
            ticket=t,
        )

    return t


@transaction.atomic
def update_ticket(pk, data):
    t = Ticket.objects.get(pk=pk)
    for field in ('reparto', 'esecutore_id', 'revisore_id', 'approvatore_id'):
        if field in data:
            setattr(t, field, data[field])
    if 'revisione_ids' in data:
        old_ids = set(t.revisioni.values_list('id', flat=True))
        new_ids = set(data['revisione_ids'])
        t.revisioni.set(new_ids)
        # Newly added revisions enter the workflow
        added = new_ids - old_ids
        if added:
            Revisione.objects.filter(id__in=added, int_status='').update(int_status='da_iniziare')
        # Removed revisions are released from the workflow
        removed = old_ids - new_ids
        if removed:
            Revisione.objects.filter(id__in=removed, int_status__in=STATI_ATTIVI_REV).update(int_status='')
    t.full_clean()
    t.save()
    return t


def delete_ticket(pk):
    ticket = Ticket.objects.get(pk=pk)
    ticket.revisioni.all().update(int_status='')
    ticket.delete()


# ── Workflow transitions (per Revisione) ─────────────────────────────────────

# Allowed transitions: (current_int_status, action) → new_int_status
_REV_TRANSITIONS = {
    ('da_iniziare', 'avvia'): 'in_lavorazione',
    ('in_lavorazione', 'sottometti'): 'in_revisione',
    ('in_revisione', 'accetta'): 'in_approvazione',
    ('in_revisione', 'rifiuta'): 'in_lavorazione',
    ('in_approvazione', 'accetta'): 'da_emettere',
    ('in_approvazione', 'rifiuta'): 'in_lavorazione',
}


def _check_rev_transition_permission(ticket, current_status, action, user):
    """
    Permissions are still ticket-level:
      - avvia / sottometti  → only the esecutore
      - accetta / rifiuta from in_revisione   → only the revisore
      - accetta / rifiuta from in_approvazione → only the approvatore
    """
    if action in {'avvia', 'sottometti'}:
        if user.pk != ticket.esecutore_id:
            raise PermissionError('Solo l\'esecutore può eseguire questa operazione.')
    elif current_status == 'in_revisione' and action in {'accetta', 'rifiuta'}:
        if user.pk != ticket.revisore_id:
            raise PermissionError('Solo il revisore può accettare o rifiutare la revisione.')
    elif current_status == 'in_approvazione' and action in {'accetta', 'rifiuta'}:
        if user.pk != ticket.approvatore_id:
            raise PermissionError('Solo l\'approvatore può approvare o rifiutare la revisione.')


@transaction.atomic
def transition_revisione(rev_pk, action, user, nota_testo=None):
    """Execute a workflow action on a single revisione. Returns (ticket, revisione)."""
    rev = Revisione.objects.select_related('documento__testata').get(pk=rev_pk)

    # Find the active ticket linked to this revisione.
    ticket = (rev.tickets
              .select_related('esecutore', 'revisore', 'approvatore')
              .order_by('-created_at')
              .first())
    if ticket is None:
        raise ValueError('Nessun ticket associato a questa revisione.')

    current = rev.int_status or ''
    new_status = _REV_TRANSITIONS.get((current, action))
    if new_status is None:
        label = dict(STATI_INTERNI_CHOICES).get(current, current or '—')
        raise ValueError(f"Azione '{action}' non consentita nello stato '{label}'.")

    _check_rev_transition_permission(ticket, current, action, user)

    rev.int_status = new_status
    rev.save(update_fields=['int_status'])

    if nota_testo:
        TicketNota.objects.create(ticket=ticket, autore=user, testo=nota_testo)

    _send_rev_transition_notifications(ticket, rev, action, new_status)

    return ticket, rev


def _send_rev_transition_notifications(ticket, rev, action, new_status):
    notifiche = []
    rev_label = f'{ticket.nome} · {rev.documento.vendor_doc or rev.documento.doc_title or "Doc"} rev {rev.rev_no}'

    if action == 'sottometti':
        notifiche.append((ticket.revisore_id, f'{rev_label}: pronta per la revisione'))
    elif action == 'accetta' and new_status == 'in_approvazione':
        notifiche.append((ticket.approvatore_id, f'{rev_label}: pronta per l\'approvazione'))
    elif action == 'accetta' and new_status == 'da_emettere':
        notifiche.append((ticket.esecutore_id, f'{rev_label}: approvata, pronta per l\'emissione'))
    elif action == 'rifiuta':
        notifiche.append((ticket.esecutore_id, f'{rev_label}: rifiutata, richieste modifiche'))

    for uid, testo in notifiche:
        Notifica.objects.create(destinatario_id=uid, testo=testo, ticket=ticket)


# ── Revisions pending emission ───────────────────────────────────────────────

def list_revisioni_da_emettere(reparto=None, commessa=None):
    """
    Return revisions that are pending ticket assignment for a department:
    1. Rev 0 of documents with a reparto that don't yet have a ticket
    2. Revisions with crea_nuova_rev=True (returned from client) without a ticket
    A revision is "in flight" when its int_status is in active or post-workflow states.
    """
    qs = Revisione.objects.select_related('documento__testata', 'ext_status').filter(
        Q(documento__reparto__gt=''),
    ).filter(
        Q(rev_no=0, int_status='') | Q(crea_nuova_rev=True, int_status=''),
    )

    if reparto:
        qs = qs.filter(documento__reparto=reparto)
    if commessa:
        qs = qs.filter(documento__testata__job__icontains=commessa)

    return [_serialize_ticket_revisione(r) for r in qs]


def count_revisioni_da_emettere_per_reparto():
    qs = Revisione.objects.filter(
        Q(documento__reparto__gt=''),
    ).filter(
        Q(rev_no=0, int_status='') | Q(crea_nuova_rev=True, int_status=''),
    )

    from django.db.models import Count
    counts = qs.values('documento__reparto').annotate(n=Count('id'))
    return {row['documento__reparto']: row['n'] for row in counts}


def count_tickets_attivi_per_reparto():
    """Tickets with at least one revisione still in an active workflow status."""
    from django.db.models import Count
    qs = (Ticket.objects
          .filter(revisioni__int_status__in=STATI_ATTIVI_REV)
          .values('reparto')
          .annotate(n=Count('id', distinct=True)))
    return {row['reparto']: row['n'] for row in qs}


# ── Notes ────────────────────────────────────────────────────────────────────

def list_note(ticket_pk):
    return [serialize_nota(n) for n in TicketNota.objects.filter(ticket_id=ticket_pk).select_related('autore')]


def create_nota(ticket_pk, user, testo):
    n = TicketNota.objects.create(ticket_id=ticket_pk, autore=user, testo=testo)
    return n


# ── Notifications ────────────────────────────────────────────────────────────

def list_notifiche(user, solo_non_lette=False):
    qs = Notifica.objects.filter(destinatario=user)
    if solo_non_lette:
        qs = qs.filter(letta=False)
    return [serialize_notifica(n) for n in qs[:50]]


def count_non_lette(user):
    return Notifica.objects.filter(destinatario=user, letta=False).count()


def mark_as_read(pk, user):
    Notifica.objects.filter(pk=pk, destinatario=user).update(letta=True)


def mark_all_as_read(user):
    Notifica.objects.filter(destinatario=user, letta=False).update(letta=True)


# ── Overview (user dashboard) ────────────────────────────────────────────────

def get_user_overview(user):
    """
    Returns the user's tickets split by:
      - action_required: tickets that have at least one revisione awaiting this user's action
      - in_corso: other tickets where the user has any role and at least one rev still in workflow
    """
    uid = user.pk

    # All tickets where the user has any role
    base = (Ticket.objects
            .select_related('esecutore', 'revisore', 'approvatore')
            .prefetch_related('revisioni')
            .filter(Q(esecutore_id=uid) | Q(revisore_id=uid) | Q(approvatore_id=uid))
            .order_by('-updated_at'))

    action_required = []
    in_corso = []

    for t in base:
        statuses = [r.int_status or '' for r in t.revisioni.all()]
        if not statuses:
            continue
        active = [s for s in statuses if s in STATI_ATTIVI_REV]
        if not active:
            continue  # ticket concluso (or not yet assigned) → skip

        needs_me = False
        if t.esecutore_id == uid and any(s in ('da_iniziare', 'in_lavorazione') for s in statuses):
            needs_me = True
        if t.revisore_id == uid and 'in_revisione' in statuses:
            needs_me = True
        if t.approvatore_id == uid and 'in_approvazione' in statuses:
            needs_me = True

        (action_required if needs_me else in_corso).append(t)

    in_corso = in_corso[:5]

    label_map = dict(STATI_INTERNI_CHOICES)

    def _role_for_user(t):
        roles = []
        if t.esecutore_id == uid:
            roles.append('Esecutore')
        if t.revisore_id == uid:
            roles.append('Revisore')
        if t.approvatore_id == uid:
            roles.append('Approvatore')
        return ', '.join(roles)

    def _mini(t):
        statuses = [r.int_status or '' for r in t.revisioni.all()]
        counts = Counter(statuses)
        return {
            'id': t.pk,
            'nome': t.nome,
            'commessa': t.commessa,
            'progressivo': t.progressivo,
            'reparto': t.reparto,
            'ruolo': _role_for_user(t),
            'updated_at': t.updated_at.isoformat() if t.updated_at else None,
            'status_counts': dict(counts),
            'status_labels': label_map,
            'totale_revisioni': len(statuses),
        }

    return {
        'action_required': [_mini(t) for t in action_required],
        'in_corso': [_mini(t) for t in in_corso],
    }
