from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from .models import Empresa

# Campos que não vale a pena exibir como alteração comum
_CAMPOS_IGNORADOS = {'deletado_em', 'deletado_por', 'atualizado_em', 'history_id', 'history_date', 'history_change_reason', 'history_type', 'history_user'}

_BOOL_LABELS = {True: 'Sim', False: 'Não', None: '—'}


def _fmt_valor(v):
    if isinstance(v, bool):
        return _BOOL_LABELS[v]
    return str(v) if v not in (None, '') else '—'


def _build_history(obj):
    """Retorna lista de entradas de histórico com tipo e campos alterados."""
    records = list(obj.history.all())
    # campos rastreáveis do modelo (excluindo os ignorados)
    tracked_fields = [
        f.name for f in obj._meta.get_fields()
        if hasattr(f, 'column') and f.name not in _CAMPOS_IGNORADOS
    ]
    entries = []

    for i, record in enumerate(records):
        alteracoes = []
        tipo = record.history_type

        if record.history_type == '~' and i < len(records) - 1:
            prev = records[i + 1]

            # detecta soft delete / restore comparando deletado_em diretamente
            curr_del = getattr(record, 'deletado_em', None)
            prev_del = getattr(prev, 'deletado_em', None)

            if prev_del is None and curr_del is not None:
                tipo = 'soft_delete'
            elif prev_del is not None and curr_del is None:
                tipo = 'restore'
            else:
                # compara campo a campo
                for fname in tracked_fields:
                    curr_val = getattr(record, fname, None)
                    prev_val = getattr(prev, fname, None)
                    if curr_val != prev_val:
                        try:
                            label = obj._meta.get_field(fname).verbose_name.capitalize()
                        except Exception:
                            label = fname
                        alteracoes.append({
                            'campo': label,
                            'de': _fmt_valor(prev_val),
                            'para': _fmt_valor(curr_val),
                        })

        entries.append({'record': record, 'tipo': tipo, 'alteracoes': alteracoes})
    return entries


class EmpresaListView(LoginRequiredMixin, ListView):
    model = Empresa
    template_name = 'core/empresa_list.html'
    context_object_name = 'empresas'
    paginate_by = 20

    def get_queryset(self):
        qs = Empresa.objects.all()
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(nome__icontains=q) | qs.filter(cnpj__icontains=q) | qs.filter(razao_social__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        ctx['total_deletadas'] = Empresa.all_objects.filter(deletado_em__isnull=False).count()
        return ctx


class EmpresaDeletedListView(LoginRequiredMixin, ListView):
    template_name = 'core/empresa_deleted_list.html'
    context_object_name = 'empresas'
    paginate_by = 20

    def get_queryset(self):
        return Empresa.all_objects.filter(deletado_em__isnull=False).order_by('-deletado_em')


class EmpresaDetailView(LoginRequiredMixin, DetailView):
    template_name = 'core/empresa_detail.html'
    context_object_name = 'empresa'

    def get_object(self):
        return get_object_or_404(Empresa.all_objects, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['history_entries'] = _build_history(self.object)
        return ctx


class EmpresaCreateView(LoginRequiredMixin, CreateView):
    model = Empresa
    template_name = 'core/empresa_form.html'
    fields = [
        'nome', 'razao_social', 'cnpj', 'email', 'telefone', 'site', 'ativo',
        'cep', 'logradouro', 'numero', 'complemento', 'bairro', 'cidade', 'estado',
    ]
    success_url = reverse_lazy('core:empresa_list')

    def form_valid(self, form):
        messages.success(self.request, 'Empresa cadastrada com sucesso.')
        return super().form_valid(form)


class EmpresaUpdateView(LoginRequiredMixin, UpdateView):
    model = Empresa
    template_name = 'core/empresa_form.html'
    fields = [
        'nome', 'razao_social', 'cnpj', 'email', 'telefone', 'site', 'ativo',
        'cep', 'logradouro', 'numero', 'complemento', 'bairro', 'cidade', 'estado',
    ]

    def get_success_url(self):
        messages.success(self.request, 'Empresa atualizada com sucesso.')
        return reverse_lazy('core:empresa_detail', kwargs={'pk': self.object.pk})


class EmpresaDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk):
        empresa = get_object_or_404(Empresa.objects, pk=pk)
        return render(request, 'core/empresa_confirm_delete.html', {'object': empresa})

    def post(self, request, pk):
        empresa = get_object_or_404(Empresa.objects, pk=pk)
        empresa.soft_delete(user=request.user)
        messages.success(request, f'Empresa "{empresa.nome}" foi excluída e pode ser restaurada.')
        return redirect('core:empresa_list')


class EmpresaRestoreView(LoginRequiredMixin, View):
    def post(self, request, pk):
        empresa = get_object_or_404(Empresa.all_objects, pk=pk, deletado_em__isnull=False)
        empresa.restaurar()
        messages.success(request, f'Empresa "{empresa.nome}" restaurada com sucesso.')
        return redirect('core:empresa_detail', pk=empresa.pk)


class EmpresaHistoricoLimparView(LoginRequiredMixin, View):
    def get(self, request, pk):
        if not request.user.is_superuser:
            return HttpResponseForbidden()
        empresa = get_object_or_404(Empresa.all_objects, pk=pk)
        total = empresa.history.count()
        return render(request, 'core/empresa_historico_limpar.html', {
            'empresa': empresa,
            'total': total,
        })

    def post(self, request, pk):
        if not request.user.is_superuser:
            return HttpResponseForbidden()
        empresa = get_object_or_404(Empresa.all_objects, pk=pk)
        periodo = request.POST.get('periodo')

        opcoes = {'30': 30, '90': 90, '180': 180, '365': 365}

        mais_recente = empresa.history.first()

        if periodo in opcoes:
            corte = timezone.now() - timezone.timedelta(days=opcoes[periodo])
            deletados = empresa.history.filter(history_date__lt=corte).delete()
            total = deletados[0] if isinstance(deletados, tuple) else deletados
            messages.success(request, f'{total} registro(s) de histórico anteriores a {opcoes[periodo]} dias foram removidos.')
        elif periodo == 'tudo':
            # mantém apenas o registro mais recente
            if mais_recente:
                empresa.history.exclude(pk=mais_recente.pk).delete()
            messages.success(request, 'Histórico limpo. O registro mais recente foi preservado.')

        return redirect('core:empresa_detail', pk=pk)


@login_required
def empresa_lista_pdf(request):
    q = request.GET.get('q', '').strip()
    qs = Empresa.objects.all()
    if q:
        qs = qs.filter(nome__icontains=q) | qs.filter(cnpj__icontains=q) | qs.filter(razao_social__icontains=q)
    return render(request, 'core/empresa_lista_pdf.html', {'empresas': qs, 'q': q})


def empresa_pdf(request, pk):
    empresa = get_object_or_404(Empresa.all_objects, pk=pk)
    return render(request, 'core/empresa_pdf.html', {'empresa': empresa})


def empresa_historico_pdf(request, pk):
    empresa = get_object_or_404(Empresa.all_objects, pk=pk)
    history_entries = _build_history(empresa)
    return render(request, 'core/empresa_historico_pdf.html', {
        'empresa': empresa,
        'history_entries': history_entries,
    })


@login_required
def selecionar_empresa(request):
    if request.method != 'POST':
        return redirect('/')

    empresa_id = request.POST.get('empresa_id')
    if not empresa_id:
        return redirect('/')

    if request.user.is_superuser:
        empresa = get_object_or_404(Empresa, pk=empresa_id, ativo=True)
    else:
        profile = getattr(request.user, 'profile', None)
        if not profile:
            return HttpResponseForbidden()
        empresa = get_object_or_404(profile.empresas, pk=empresa_id, ativo=True)

    request.session['empresa_id'] = empresa.pk
    return redirect('/')


@login_required
def sem_empresa(request):
    return render(request, 'core/sem_empresa.html')
