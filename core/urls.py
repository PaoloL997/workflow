from django.urls import path

from . import views

urlpatterns = [
    # HTML — Auth
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    # HTML — Home
    path("", views.home_view, name="home"),
    path("profilo/", views.profilo_view, name="profilo"),
    path("commesse/", views.commesse_list_view, name="commesse_list"),
    path("commesse/<str:job>/", views.commessa_detail_view, name="commessa_detail"),
    path("commesse/<str:job>/documenti/", views.documenti_list_view, name="documenti_list"),
    path("commesse/<str:job>/archivio/", views.archivio_detail_view, name="archivio_detail"),
    path("commesse/<str:job>/emissione/", views.emissione_detail_view, name="emissione_detail"),
    path("commesse/<str:job>/ricezione/", views.ricezione_detail_view, name="ricezione_detail"),
    path("commesse/<str:job>/situazione/", views.situazione_detail_view, name="situazione_detail"),
    # API — Commesse
    path("api/commesse/", views.commesse_api, name="commesse_api"),
    path("api/commesse/<str:job>/", views.commessa_api_detail, name="commessa_api_detail"),
    path("api/erp/", views.erp_api, name="erp_api"),
    # API — Indirizzi di spedizione
    path("api/commesse/<str:job>/indirizzi/", views.indirizzi_api, name="indirizzi_api"),
    path("api/indirizzi/<int:pk>/", views.indirizzo_api_detail, name="indirizzo_api_detail"),
    # API — Documenti
    path("api/commesse/<str:job>/documenti/", views.documenti_api, name="documenti_api"),
    path("api/commesse/<str:job>/export/", views.export_documenti, name="export_documenti"),
    path(
        "api/commesse/<str:job>/situazione/export/",
        views.export_situazione,
        name="export_situazione",
    ),
    path(
        "api/commesse/<str:job>/import-excel/",
        views.import_documenti_excel,
        name="import_documenti_excel",
    ),
    path(
        "api/commesse/<str:job>/genera-da-modelli/",
        views.genera_documenti_da_modelli_api,
        name="genera_documenti_da_modelli_api",
    ),
    path("api/documenti/<int:pk>/", views.documento_api_detail, name="documento_api_detail"),
    # API — Reparti (read-only, from User.reparto)
    path("api/reparti/", views.reparti_api, name="reparti_api"),
    path("api/cartelle-modelli/", views.cartelle_modelli_api, name="cartelle_modelli_api"),
    # API — Stati (interni read-only, esterni CRUD)
    path("api/stati-interni/", views.stati_interni_api, name="stati_interni_api"),
    path("api/stati-esterni/", views.stati_esterni_api, name="stati_esterni_api"),
    path(
        "api/stati-esterni/<int:pk>/",
        views.stato_esterno_api_detail,
        name="stato_esterno_api_detail",
    ),
    # API — Stabilimenti
    path("api/stabilimenti/", views.stabilimenti_api, name="stabilimenti_api"),
    # API — Emissione
    path("api/emissione/", views.emissione_api, name="emissione_api"),
    path("api/trasmittal/pdf/", views.trasmittal_pdf_api, name="trasmittal_pdf_api"),
    # API — Ricezione
    path("api/ricezione/", views.ricezione_api, name="ricezione_api"),
    # API — Revisioni (usate dalla ricezione per creare nuova revisione)
    path("api/documenti/<int:doc_pk>/revisioni/", views.revisioni_api, name="revisioni_api"),
    path("api/revisioni/<int:pk>/", views.revisione_api_detail, name="revisione_api_detail"),
    # API — File revisione
    path("api/revisioni/<int:pk>/file/", views.revisione_file_api, name="revisione_file_api"),
    path(
        "api/revisioni/<int:pk>/file/serve/",
        views.revisione_file_serve,
        name="revisione_file_serve",
    ),
    path(
        "api/revisioni/<int:pk>/file/link/",
        views.revisione_file_link_api,
        name="revisione_file_link_api",
    ),
    path("api/fileserver/browse/", views.fileserver_browse_api, name="fileserver_browse_api"),
    # HTML + API — Import from old Access DB
    path("import-from-old/", views.import_from_old_view, name="import_from_old"),
    path("api/import-from-old/", views.import_from_old_api, name="import_from_old_api"),
]
