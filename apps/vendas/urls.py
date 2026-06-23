from django.urls import path
from . import views

app_name = 'vendas'

urlpatterns = [
    path('empreendimentos/<int:pk>/tabelas/', views.TabelaVendasListView.as_view(), name='tabela_list'),
    path('empreendimentos/<int:pk>/tabelas/nova/', views.TabelaVendasCreateView.as_view(), name='tabela_create'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/', views.TabelaVendasDetailView.as_view(), name='tabela_detail'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/editar/', views.TabelaVendasUpdateView.as_view(), name='tabela_update'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/excluir/', views.TabelaVendasDeleteView.as_view(), name='tabela_delete'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/pdf/', views.tabela_pdf, name='tabela_pdf'),
    path('empreendimentos/<int:pk>/tabelas/<int:tabela_pk>/itens/<int:item_pk>/editar/', views.TabelaVendasItemUpdateView.as_view(), name='tabela_item_update'),
]
