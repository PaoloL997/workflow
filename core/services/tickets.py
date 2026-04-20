"""
Business logic for Ticket, TicketNota, and Notifica management.
Includes CRUD operations and workflow state transitions.
"""

from django.db import transaction
from django.db.models import Q

from ..models import (
    Ticket, TicketNota, Notifica, Revisione, Documento, User,
    STATO_TICKET_CHOICES,
)


# ── Serializers ──────────────────────────────────────────────────────────────

def serialize_ticket(t):
    from ..models import Testata
    testata = None
    if t.commessa:
        testata = Testata.objects.filter(job=t.commessa).first()
    return {
        'id': t.pk,
        'nome': t.nome,
        'commessa': t.commessa,
        'progressivo': t.progressivo,
        'reparto': t.reparto,
        'esecutore': {'id': t.esecutore_id, 'username': t.esecutore.username},
        'revisore': {'id': t.revisore_id, 'username': t.revisore.username},
        'approvatore': {'id': t.approvatore_id, 'username': t.approvatore.username},
        'stato': t.stato,
        'stato_label': t.get_stato_display(),
        'revisioni': [_serialize_ticket_revisione(r) for r in t.revisioni.select_related('documento__testata', 'ext_status')],
        'created_at': t.created_at.isoformat() if t.created_at else None,
        'updated_at': t.updated_at.isoformat() if t.updated_at else None,
        'cliente': testata.client if testata else '',
        'descrizione_commessa': testata.job_detail if testata else '',
        'consegna': testata.delivery_date.strftime('%d/%m/%Y') if testata and testata.delivery_date else '',
    }


def _serialize_ticket_revisione(r):
    from ..models import STATI_INTERNI_CHOICES
    label_map = dict(STATI_INTERNI_CHOICES)
    return {
        'id': r.pk,
        'documento_id': r.documento_id,
        'job': r.documento.testata_id,
        'doc_title': r.documento.doc_title,
        'vendor_doc': r.documento.vendor_doc,
        'rev_no': r.rev_no,
        'int_status': r.int_status,
        'int_status_label': label_map.get(r.int_status, r.int_status),
        'ext_status_label': r.ext_status.nome if r.ext_status else '',
        'reparto_nome': r.documento.reparto or '',
    }


def serialize_nota(n):
    return {
        'id': n.pk,
        'ticket_id': n.ticket_id,
        'autore': n.autore.username if n.autore else None,
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

def list_tickets(reparto=None, stato=None, commessa=None):
    qs = Ticket.objects.select_related('esecutore', 'revisore', 'approvatore')
    if reparto:
        qs = qs.filter(reparto=reparto)
    if stato:
        qs = qs.filter(stato=stato)
    if commessa:
        qs = qs.filter(
            revisioni__documento__testata__job__icontains=commessa
        ).distinct()
    return [serialize_ticket(t) for t in qs]


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
            commessa = jobs[0]  # Use first commessa found

    # Compute next progressivo for this commessa
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
        stato='da_iniziare',
    )
    t.full_clean()
    t.save()

    if revisione_ids:
        t.revisioni.set(revisione_ids)

    # Notify the three assignees
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
        t.revisioni.set(data['revisione_ids'])
    t.full_clean()
    t.save()
    return t


def delete_ticket(pk):
    ticket = Ticket.objects.get(pk=pk)
    ticket.revisioni.all().update(int_status='')
    ticket.delete()


# ── Workflow transitions ─────────────────────────────────────────────────────

# Allowed transitions: (current_state, action) → new_state
_TRANSITIONS = {
    ('da_iniziare', 'avvia'): 'in_lavorazione',
    ('in_lavorazione', 'sottometti'): 'in_revisione',
    ('in_revisione', 'accetta'): 'in_approvazione',
    ('in_revisione', 'rifiuta'): 'in_lavorazione',
    ('in_approvazione', 'accetta'): 'concluso',
    ('in_approvazione', 'rifiuta'): 'in_lavorazione',
}


def _check_transition_permission(ticket, action, user):
    """
    Raise PermissionError if the user is not allowed to perform the action.
    Rules:
      - avvia / sottometti  → only the esecutore
      - accetta / rifiuta from in_revisione   → only the revisore
      - accetta / rifiuta from in_approvazione → only the approvatore
    """
    esecutore_actions = {'avvia', 'sottometti'}
    revisore_states = {'in_revisione'}
    approvatore_states = {'in_approvazione'}

    if action in esecutore_actions:
        if user.pk != ticket.esecutore_id:
            raise PermissionError('Solo l\'esecutore può eseguire questa operazione.')
    elif ticket.stato in revisore_states and action in {'accetta', 'rifiuta'}:
        if user.pk != ticket.revisore_id:
            raise PermissionError('Solo il revisore può accettare o rifiutare la revisione.')
    elif ticket.stato in approvatore_states and action in {'accetta', 'rifiuta'}:
        if user.pk != ticket.approvatore_id:
            raise PermissionError('Solo l\'approvatore può approvare o rifiutare il ticket.')


@transaction.atomic
def transition_ticket(pk, action, user, nota_testo=None):
    """Execute a workflow action on a ticket. Returns updated ticket."""
    t = Ticket.objects.select_related(
        'esecutore', 'revisore', 'approvatore'
    ).get(pk=pk)

    key = (t.stato, action)
    new_stato = _TRANSITIONS.get(key)
    if new_stato is None:
        raise ValueError(
            f"Azione '{action}' non consentita nello stato '{t.get_stato_display()}'."
        )

    _check_transition_permission(t, action, user)

    old_stato = t.stato
    t.stato = new_stato
    t.save()

    # Update linked revisions' int_status to mirror ticket state
    _sync_revisioni_status(t)

    # Add optional note
    if nota_testo:
        TicketNota.objects.create(ticket=t, autore=user, testo=nota_testo)

    # Send notifications based on transition
    _send_transition_notifications(t, action, user)

    return t


def _sync_revisioni_status(ticket):
    """Keep linked revisions' int_status aligned with ticket state."""
    mapping = {
        'da_iniziare': 'da_iniziare',
        'in_lavorazione': 'in_lavorazione',
        'in_revisione': 'in_revisione',
        'in_approvazione': 'in_approvazione',
        'concluso': 'da_emettere',
    }
    new_status = mapping.get(ticket.stato)
    if new_status:
        ticket.revisioni.update(int_status=new_status)


def _send_transition_notifications(ticket, action, actor):
    """Create in-app notifications for relevant users after a transition."""
    notifiche = []

    if action == 'avvia':
        pass  # Esecutore started, no extra notification needed

    elif action == 'sottometti':
        notifiche.append((
            ticket.revisore_id,
            f'Ticket {ticket.nome}: pronto per la revisione',
        ))

    elif action == 'accetta' and ticket.stato == 'in_approvazione':
        notifiche.append((
            ticket.approvatore_id,
            f'Ticket {ticket.nome}: pronto per l\'approvazione',
        ))

    elif action == 'accetta' and ticket.stato == 'concluso':
        notifiche.append((
            ticket.esecutore_id,
            f'Ticket {ticket.nome}: approvato e concluso',
        ))

    elif action == 'rifiuta':
        notifiche.append((
            ticket.esecutore_id,
            f'Ticket {ticket.nome}: rifiutato, richieste modifiche',
        ))

    for uid, testo in notifiche:
        Notifica.objects.create(
            destinatario_id=uid,
            testo=testo,
            ticket=ticket,
        )


# ── Revisions pending emission ───────────────────────────────────────────────

def list_revisioni_da_emettere(reparto=None, commessa=None):
    """
    Return revisions that are pending ticket assignment for a department:
    1. Rev 0 of documents with a reparto that don't have an active ticket
    2. Revisions with crea_nuova_rev=True that don't have an active ticket
    """
    active_ticket_rev_ids = Revisione.objects.filter(
        tickets__stato__in=['da_iniziare', 'in_lavorazione', 'in_revisione', 'in_approvazione']
    ).values_list('id', flat=True)

    qs = Revisione.objects.select_related('documento__testata', 'ext_status').filter(
        Q(documento__reparto__gt=''),  # Only docs with a reparto
    ).exclude(
        id__in=active_ticket_rev_ids,
    ).exclude(
        int_status__in=['inviato_al_cliente', 'da_emettere'],
    ).filter(
        Q(rev_no=0, int_status='') |  # Newly created rev 0
        Q(crea_nuova_rev=True),       # Return from client
    )

    if reparto:
        qs = qs.filter(documento__reparto=reparto)

    if commessa:
        qs = qs.filter(documento__testata__job__icontains=commessa)

    return [_serialize_ticket_revisione(r) for r in qs]


def count_revisioni_da_emettere_per_reparto():
    """Return {reparto_name: count} for sidebar badge counts."""
    active_ticket_rev_ids = Revisione.objects.filter(
        tickets__stato__in=['da_iniziare', 'in_lavorazione', 'in_revisione', 'in_approvazione']
    ).values_list('id', flat=True)

    qs = Revisione.objects.filter(
        Q(documento__reparto__gt=''),
    ).exclude(
        id__in=active_ticket_rev_ids,
    ).exclude(
        int_status__in=['inviato_al_cliente', 'da_emettere'],
    ).filter(
        Q(rev_no=0, int_status='') |
        Q(crea_nuova_rev=True),
    )

    from django.db.models import Count
    counts = qs.values('documento__reparto').annotate(n=Count('id'))
    return {row['documento__reparto']: row['n'] for row in counts}


def count_tickets_attivi_per_reparto():
    """Return {reparto_name: count} for tickets not yet concluded."""
    from django.db.models import Count
    counts = Ticket.objects.exclude(
        stato='concluso'
    ).values('reparto').annotate(n=Count('id'))
    return {row['reparto']: row['n'] for row in counts}


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
    Return a summary of the user's ticket activity:
    - action_required: tickets where the user must act now
    - in_corso: other active tickets where the user is involved
    """
    uid = user.pk
    active_states = ['da_iniziare', 'in_lavorazione', 'in_revisione', 'in_approvazione']

    # Tickets that need this user's action right now
    action_qs = Ticket.objects.select_related(
        'esecutore', 'revisore', 'approvatore'
    ).filter(
        Q(esecutore_id=uid, stato__in=['da_iniziare', 'in_lavorazione']) |
        Q(revisore_id=uid, stato='in_revisione') |
        Q(approvatore_id=uid, stato='in_approvazione')
    ).order_by('-updated_at')

    action_ids = set(action_qs.values_list('pk', flat=True))

    # Other active tickets involving the user (any role) that don't need their action
    other_qs = Ticket.objects.select_related(
        'esecutore', 'revisore', 'approvatore'
    ).filter(
        Q(esecutore_id=uid) | Q(revisore_id=uid) | Q(approvatore_id=uid),
        stato__in=active_states,
    ).exclude(pk__in=action_ids).order_by('-updated_at')[:5]

    def _role_for_user(t, uid):
        roles = []
        if t.esecutore_id == uid:
            roles.append('Esecutore')
        if t.revisore_id == uid:
            roles.append('Revisore')
        if t.approvatore_id == uid:
            roles.append('Approvatore')
        return ', '.join(roles)

    def _mini(t):
        return {
            'id': t.pk,
            'nome': t.nome,
            'commessa': t.commessa,
            'reparto': t.reparto,
            'stato': t.stato,
            'stato_label': t.get_stato_display(),
            'ruolo': _role_for_user(t, uid),
            'updated_at': t.updated_at.isoformat() if t.updated_at else None,
        }

    return {
        'action_required': [_mini(t) for t in action_qs],
        'in_corso': [_mini(t) for t in other_qs],
    }
