from django.urls import path
from . import views

app_name = 'reservas'

urlpatterns = [
    # Espelho de unidades
    path('empreendimentos/<int:pk>/espelho/', views.EspelhoView.as_view(), name='espelho'),
    # Kanban
    path('reservas/', views.NegociacaoKanbanView.as_view(), name='kanban'),
    # Reserva CRUD
    path('reservas/nova/', views.NegociacaoCreateView.as_view(), name='negociacao_create'),
    path('reservas/<int:pk>/', views.NegociacaoDetailView.as_view(), name='negociacao_detail'),
    path('reservas/<int:pk>/editar/', views.NegociacaoUpdateView.as_view(), name='negociacao_update'),
    path('reservas/<int:pk>/excluir/', views.NegociacaoDeleteView.as_view(), name='negociacao_delete'),
    # Avanço de etapa
    path('reservas/<int:pk>/avancar/', views.avancar_etapa, name='avancar_etapa'),
    # API sugestões
    path('reservas/api/conjuge/<int:pessoa_pk>/', views.api_conjuge_sugerido, name='api_conjuge_sugerido'),
    # Unidades
    path('reservas/<int:pk>/change-tabela/', views.negociacao_change_tabela, name='negociacao_change_tabela'),
    path('reservas/<int:pk>/nova-proposta/', views.negociacao_nova_rodada, name='negociacao_nova_rodada'),
    path('reservas/<int:pk>/propostas/<int:rodada_pk>/aprovar/', views.negociacao_aprovar_rodada, name='negociacao_aprovar_rodada'),
    path('reservas/<int:pk>/reset-series/', views.negociacao_reset_series, name='negociacao_reset_series'),
    path('reservas/<int:pk>/unidades/adicionar/', views.negociacao_unidade_add, name='negociacao_unidade_add'),
    path('reservas/<int:pk>/unidades/<int:nu_pk>/remover/', views.negociacao_unidade_remove, name='negociacao_unidade_remove'),
    # Partes
    path('reservas/<int:pk>/partes/adicionar/', views.parte_add, name='parte_add'),
    path('reservas/<int:pk>/partes/<int:parte_pk>/remover/', views.parte_remove, name='parte_remove'),
    # Séries
    path('reservas/<int:pk>/series/adicionar/', views.serie_add, name='serie_add'),
    path('reservas/<int:pk>/series/<int:serie_pk>/editar/', views.serie_update, name='serie_update'),
    path('reservas/<int:pk>/series/<int:serie_pk>/remover/', views.serie_remove, name='serie_remove'),
    # Config Tipos de Parte
    path('configuracoes/tipos-parte/', views.TipoParteListView.as_view(), name='tipo_parte_list'),
    path('configuracoes/tipos-parte/novo/', views.TipoParteCreateView.as_view(), name='tipo_parte_create'),
    path('configuracoes/tipos-parte/<int:pk>/editar/', views.TipoParteUpdateView.as_view(), name='tipo_parte_update'),
    path('configuracoes/tipos-parte/<int:pk>/excluir/', views.TipoParteDeleteView.as_view(), name='tipo_parte_delete'),
    # Config Workflow
    path('configuracoes/workflow/', views.EtapaWorkflowListView.as_view(), name='etapa_list'),
    path('configuracoes/workflow/reordenar/', views.reordenar_etapas, name='etapa_reordenar'),
    path('configuracoes/workflow/nova/', views.EtapaWorkflowCreateView.as_view(), name='etapa_create'),
    path('configuracoes/workflow/<int:pk>/editar/', views.EtapaWorkflowUpdateView.as_view(), name='etapa_update'),
    path('configuracoes/workflow/<int:pk>/excluir/', views.EtapaWorkflowDeleteView.as_view(), name='etapa_delete'),
    path('configuracoes/workflow/<int:pk>/transicoes/', views.transicoes_view, name='transicoes'),
    path('configuracoes/workflow/<int:origem_pk>/transicoes/<int:destino_pk>/toggle/', views.transicao_toggle, name='transicao_toggle'),
]
