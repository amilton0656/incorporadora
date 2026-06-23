from django.urls import path
from . import views

app_name = 'pessoas'

urlpatterns = [
    # Pessoas
    path('pessoas/', views.PessoaListView.as_view(), name='pessoa_list'),
    path('pessoas/pdf/', views.pessoa_lista_pdf, name='pessoa_lista_pdf'),
    path('pessoas/nova/', views.PessoaCreateView.as_view(), name='pessoa_create'),
    path('pessoas/<int:pk>/', views.PessoaDetailView.as_view(), name='pessoa_detail'),
    path('pessoas/<int:pk>/editar/', views.PessoaUpdateView.as_view(), name='pessoa_update'),
    path('pessoas/<int:pk>/excluir/', views.PessoaDeleteView.as_view(), name='pessoa_delete'),
    path('pessoas/<int:pk>/restaurar/', views.PessoaRestoreView.as_view(), name='pessoa_restore'),
    path('pessoas/<int:pk>/pdf/', views.pessoa_pdf, name='pessoa_pdf'),
    path('pessoas/<int:pk>/papeis/adicionar/', views.papel_add, name='papel_add'),
    path('pessoas/<int:pk>/papeis/<int:papel_pk>/remover/', views.papel_remove, name='papel_remove'),
    # Configurações
    path('configuracoes/tipo-papel/', views.TipoPapelListView.as_view(), name='tipo_papel_list'),
    path('configuracoes/tipo-papel/pdf/', views.tipo_papel_lista_pdf, name='tipo_papel_lista_pdf'),
    path('configuracoes/tipo-papel/novo/', views.TipoPapelCreateView.as_view(), name='tipo_papel_create'),
    path('configuracoes/tipo-papel/<int:pk>/editar/', views.TipoPapelUpdateView.as_view(), name='tipo_papel_update'),
    path('configuracoes/tipo-papel/<int:pk>/excluir/', views.TipoPapelDeleteView.as_view(), name='tipo_papel_delete'),
]
