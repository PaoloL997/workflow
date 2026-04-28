from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('registrazione/', views.register_view, name='register'),
    # Pages
    path('gestione-documenti/', views.gestione_documenti, name='gestione_documenti'),
    path('gestione-ticket/', views.gestione_ticket, name='gestione_ticket'),
    path('gestione-ticket/<int:pk>/', views.ticket_detail_view, name='ticket_detail'),
    path('impostazioni/', views.impostazioni, name='impostazioni'),
    # API — Commesse
    path('api/commesse/', views.commesse_api, name='commesse_api'),
    path('api/commesse/<str:job>/', views.commessa_api_detail, name='commessa_api_detail'),
    path('api/erp/', views.erp_api, name='erp_api'),
    # API — Indirizzi di spedizione
    path('api/commesse/<str:job>/indirizzi/', views.indirizzi_api, name='indirizzi_api'),
    path('api/indirizzi/<int:pk>/', views.indirizzo_api_detail, name='indirizzo_api_detail'),
    # API — Documenti
    path('api/commesse/<str:job>/documenti/', views.documenti_api, name='documenti_api'),
    path('api/commesse/<str:job>/export/', views.export_documenti, name='export_documenti'),
    path('api/commesse/<str:job>/import-excel/', views.import_documenti_excel, name='import_documenti_excel'),
    path('api/documenti/<int:pk>/', views.documento_api_detail, name='documento_api_detail'),
    # API — Reparti (read-only, from User.reparto)
    path('api/reparti/', views.reparti_api, name='reparti_api'),
    # API — Stati (interni read-only, esterni CRUD)
    path('api/stati-interni/', views.stati_interni_api, name='stati_interni_api'),
    path('api/stati-esterni/', views.stati_esterni_api, name='stati_esterni_api'),
    path('api/stati-esterni/<int:pk>/', views.stato_esterno_api_detail, name='stato_esterno_api_detail'),
    # API — Emissione
    path('api/emissione/', views.emissione_api, name='emissione_api'),
    path('api/trasmittal/pdf/', views.trasmittal_pdf_api, name='trasmittal_pdf_api'),
    # API — Ricezione
    path('api/ricezione/', views.ricezione_api, name='ricezione_api'),
    # API — Revisioni
    path('api/documenti/<int:doc_pk>/revisioni/', views.revisioni_api, name='revisioni_api'),
    path('api/revisioni/<int:pk>/', views.revisione_api_detail, name='revisione_api_detail'),
    # API — Ticket
    path('api/tickets/', views.tickets_api, name='tickets_api'),
    path('api/tickets/<int:pk>/', views.ticket_api_detail, name='ticket_api_detail'),
    path('api/revisioni/<int:pk>/transition/', views.revisione_transition_api, name='revisione_transition_api'),
    path('api/tickets/<int:pk>/note/', views.ticket_note_api, name='ticket_note_api'),
    path('api/revisioni-da-emettere/', views.revisioni_da_emettere_api, name='revisioni_da_emettere_api'),
    path('api/ticket-counts/', views.ticket_counts_api, name='ticket_counts_api'),
    # API — Notifiche
    path('api/notifiche/', views.notifiche_api, name='notifiche_api'),
    path('api/notifiche/leggi-tutte/', views.notifiche_leggi_tutte_api, name='notifiche_leggi_tutte_api'),
    path('api/notifiche/<int:pk>/leggi/', views.notifica_leggi_api, name='notifica_leggi_api'),
    # API — Users
    path('api/users/', views.users_api, name='users_api'),
    # API — Overview
    path('api/overview/', views.overview_api, name='overview_api'),
]

