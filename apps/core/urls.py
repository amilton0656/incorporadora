from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('empresas/', views.EmpresaListView.as_view(), name='empresa_list'),
    path('empresas/pdf/', views.empresa_lista_pdf, name='empresa_lista_pdf'),
    path('empresas/nova/', views.EmpresaCreateView.as_view(), name='empresa_create'),
    path('empresas/<int:pk>/', views.EmpresaDetailView.as_view(), name='empresa_detail'),
    path('empresas/<int:pk>/editar/', views.EmpresaUpdateView.as_view(), name='empresa_update'),
    path('empresas/<int:pk>/excluir/', views.EmpresaDeleteView.as_view(), name='empresa_delete'),
    path('empresas/<int:pk>/restaurar/', views.EmpresaRestoreView.as_view(), name='empresa_restore'),
    path('empresas/<int:pk>/historico/limpar/', views.EmpresaHistoricoLimparView.as_view(), name='empresa_historico_limpar'),
    path('empresas/<int:pk>/pdf/', views.empresa_pdf, name='empresa_pdf'),
    path('empresas/<int:pk>/historico/pdf/', views.empresa_historico_pdf, name='empresa_historico_pdf'),
    path('empresas/excluidas/', views.EmpresaDeletedListView.as_view(), name='empresa_deleted_list'),
    path('selecionar-empresa/', views.selecionar_empresa, name='selecionar_empresa'),
    path('sem-empresa/', views.sem_empresa, name='sem_empresa'),
]
