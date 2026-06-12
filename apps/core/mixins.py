from django.contrib import messages
from django.shortcuts import redirect
from .models import Empresa


class EmpresaQuerysetMixin:
    """Filtra o queryset pela empresa ativa na sessão."""

    empresa_field = 'empresa'

    def dispatch(self, request, *args, **kwargs):
        if not request.session.get('empresa_id'):
            messages.warning(request, 'Selecione uma empresa antes de continuar.')
            return redirect('/')
        return super().dispatch(request, *args, **kwargs)

    def get_empresa_atual(self):
        empresa_id = self.request.session.get('empresa_id')
        empresa = Empresa.objects.filter(pk=empresa_id).first()
        if not empresa:
            return None
        return empresa

    def get_queryset(self):
        empresa = self.get_empresa_atual()
        if not empresa:
            return super().get_queryset().none()
        return super().get_queryset().filter(
            **{self.empresa_field: empresa}
        )
