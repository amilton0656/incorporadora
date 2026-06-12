from django.urls import path
from . import views

app_name = 'empreendimentos'

urlpatterns = [
    # Empreendimentos
    path('empreendimentos/', views.EmpreendimentoListView.as_view(), name='empreendimento_list'),
    path('empreendimentos/pdf/', views.empreendimento_lista_pdf, name='empreendimento_lista_pdf'),
    path('empreendimentos/novo/', views.EmpreendimentoCreateView.as_view(), name='empreendimento_create'),
    path('empreendimentos/<int:pk>/', views.EmpreendimentoDetailView.as_view(), name='empreendimento_detail'),
    path('empreendimentos/<int:pk>/editar/', views.EmpreendimentoUpdateView.as_view(), name='empreendimento_update'),
    path('empreendimentos/<int:pk>/excluir/', views.EmpreendimentoDeleteView.as_view(), name='empreendimento_delete'),
    path('empreendimentos/<int:pk>/restaurar/', views.EmpreendimentoRestoreView.as_view(), name='empreendimento_restore'),
    path('empreendimentos/<int:pk>/pdf/', views.empreendimento_pdf, name='empreendimento_pdf'),
    # Blocos
    path('empreendimentos/<int:pk>/blocos/novo/', views.BlocoCreateView.as_view(), name='bloco_create'),
    path('empreendimentos/<int:pk>/blocos/<int:bloco_pk>/', views.BlocoDetailView.as_view(), name='bloco_detail'),
    path('empreendimentos/<int:pk>/blocos/<int:bloco_pk>/editar/', views.BlocoUpdateView.as_view(), name='bloco_update'),
    path('empreendimentos/<int:pk>/blocos/<int:bloco_pk>/excluir/', views.BlocoDeleteView.as_view(), name='bloco_delete'),
    # Unidades
    path('empreendimentos/<int:pk>/blocos/<int:bloco_pk>/unidades/nova/', views.UnidadeCreateView.as_view(), name='unidade_create'),
    path('empreendimentos/<int:pk>/blocos/<int:bloco_pk>/unidades/<int:unidade_pk>/', views.UnidadeDetailView.as_view(), name='unidade_detail'),
    path('empreendimentos/<int:pk>/blocos/<int:bloco_pk>/unidades/<int:unidade_pk>/editar/', views.UnidadeUpdateView.as_view(), name='unidade_update'),
    path('empreendimentos/<int:pk>/blocos/<int:bloco_pk>/unidades/<int:unidade_pk>/excluir/', views.UnidadeDeleteView.as_view(), name='unidade_delete'),
    path('empreendimentos/<int:pk>/blocos/<int:bloco_pk>/unidades/<int:unidade_pk>/pdf/', views.unidade_pdf, name='unidade_pdf'),
    # Importação
    path('empreendimentos/<int:pk>/importar-unidades/', views.importar_unidades, name='importar_unidades'),
    # Configurações
    path('configuracoes/status-unidade/', views.StatusUnidadeListView.as_view(), name='status_unidade_list'),
    path('configuracoes/status-unidade/novo/', views.StatusUnidadeCreateView.as_view(), name='status_unidade_create'),
    path('configuracoes/status-unidade/<int:pk>/editar/', views.StatusUnidadeUpdateView.as_view(), name='status_unidade_update'),
    path('configuracoes/status-unidade/<int:pk>/excluir/', views.StatusUnidadeDeleteView.as_view(), name='status_unidade_delete'),
    path('configuracoes/tipo-unidade/', views.TipoUnidadeListView.as_view(), name='tipo_unidade_list'),
    path('configuracoes/tipo-unidade/novo/', views.TipoUnidadeCreateView.as_view(), name='tipo_unidade_create'),
    path('configuracoes/tipo-unidade/<int:pk>/editar/', views.TipoUnidadeUpdateView.as_view(), name='tipo_unidade_update'),
    path('configuracoes/tipo-unidade/<int:pk>/excluir/', views.TipoUnidadeDeleteView.as_view(), name='tipo_unidade_delete'),
]
