from django.contrib import admin
from .models import Empresa, UserProfile


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'razao_social', 'cnpj', 'cidade', 'estado', 'ativo')
    list_filter = ('ativo', 'estado')
    search_fields = ('nome', 'razao_social', 'cnpj')
    fieldsets = (
        ('Identificação', {
            'fields': ('nome', 'razao_social', 'cnpj', 'email', 'telefone', 'site', 'ativo')
        }),
        ('Endereço', {
            'fields': ('cep', 'logradouro', 'numero', 'complemento', 'bairro', 'cidade', 'estado')
        }),
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'cargo')
    search_fields = ('user__username', 'user__first_name', 'user__last_name')
    filter_horizontal = ('empresas',)
