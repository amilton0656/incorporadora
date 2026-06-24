from django.urls import path
from . import views

app_name = 'vendas'

urlpatterns = [
    # Tabela de Vendas
    path('empreendimentos/<int:pk>/tabelas/', views.TabelaVendasListView.as_view(), name='tabela_list'),
    path('empreendimentos/<int:pk>/tabelas/nova/', views.TabelaVendasCreateView.as_view(), name='tabela_create'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/', views.TabelaVendasDetailView.as_view(), name='tabela_detail'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/editar/', views.TabelaVendasUpdateView.as_view(), name='tabela_update'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/excluir/', views.TabelaVendasDeleteView.as_view(), name='tabela_delete'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/pdf/', views.tabela_pdf, name='tabela_pdf'),
    # Séries
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/series/nova/', views.TabelaSerieCreateView.as_view(), name='serie_create'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/series/<int:serie_pk>/editar/', views.TabelaSerieUpdateView.as_view(), name='serie_update'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/series/<int:serie_pk>/excluir/', views.TabelaSerieDeleteView.as_view(), name='serie_delete'),
    # Itens
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/itens/<int:item_pk>/editar/', views.TabelaVendasItemUpdateView.as_view(), name='tabela_item_update'),
    # Importação CSV e recálculo
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/importar/', views.tabela_importar_csv, name='tabela_importar_csv'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/modelo-csv/', views.tabela_modelo_csv, name='tabela_modelo_csv'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/recalcular/', views.tabela_recalcular, name='tabela_recalcular'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/limpar-complementares/', views.TabelaLimparComplementaresView.as_view(), name='tabela_limpar_complementares'),
]
