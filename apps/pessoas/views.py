from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.core.mixins import EmpresaQuerysetMixin
from apps.core.models import Empresa
from apps.core.pdf import render_to_pdf
from .models import Pessoa, PessoaPapel, RepresentanteLegal, TipoPapel

_CAMPOS_IGNORADOS = {
    'deletado_em', 'deletado_por', 'atualizado_em',
    'history_id', 'history_date', 'history_change_reason', 'history_type', 'history_user',
}
_BOOL_LABELS = {True: 'Sim', False: 'Não', None: '—'}

_INPUT = (
    'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm '
    'focus:outline-none focus:ring-2 focus:ring-brand focus:border-transparent transition'
)
_INPUT_ERR = _INPUT.replace('border-gray-300', 'border-red-400')
_SELECT = _INPUT + ' bg-white'
_SELECT_ERR = _INPUT_ERR + ' bg-white'
_CHECKBOX = 'w-4 h-4 text-brand border-gray-300 rounded focus:ring-brand'


def _fmt_valor(v):
    if isinstance(v, bool):
        return _BOOL_LABELS[v]
    return str(v) if v not in (None, '') else '—'


def _build_history(obj):
    records = list(obj.history.all())
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
            curr_del = getattr(record, 'deletado_em', None)
            prev_del = getattr(prev, 'deletado_em', None)
            if prev_del is None and curr_del is not None:
                tipo = 'soft_delete'
            elif prev_del is not None and curr_del is None:
                tipo = 'restore'
            else:
                for fname in tracked_fields:
                    curr_val = getattr(record, fname, None)
                    prev_val = getattr(prev, fname, None)
                    if curr_val != prev_val:
                        try:
                            label = obj._meta.get_field(fname).verbose_name.capitalize()
                        except Exception:
                            label = fname
                        alteracoes.append({'campo': label, 'de': _fmt_valor(prev_val), 'para': _fmt_valor(curr_val)})
        entries.append({'record': record, 'tipo': tipo, 'alteracoes': alteracoes})
    return entries


def _get_empresa_atual(request):
    empresa_id = request.session.get('empresa_id')
    if not empresa_id:
        return None
    return Empresa.objects.filter(pk=empresa_id).first()


def _style_form(form):
    for fname, field in form.fields.items():
        has_error = form.is_bound and fname in form.errors
        widget = field.widget
        if isinstance(widget, (django_forms.Select, django_forms.SelectMultiple)):
            widget.attrs['class'] = _SELECT_ERR if has_error else _SELECT
        elif isinstance(widget, django_forms.CheckboxInput):
            widget.attrs['class'] = _CHECKBOX
        else:
            widget.attrs['class'] = _INPUT_ERR if has_error else _INPUT
    return form


# ─── TipoPapel (Configurações) ─────────────────────────────────────────────────

class TipoPapelListView(LoginRequiredMixin, EmpresaQuerysetMixin, ListView):
    model = TipoPapel
    template_name = 'pessoas/config_tipo_papel_list.html'
    context_object_name = 'tipos'


class TipoPapelCreateView(LoginRequiredMixin, CreateView):
    model = TipoPapel
    template_name = 'pessoas/config_form.html'
    fields = ['nome']
    success_url = reverse_lazy('pessoas:tipo_papel_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        form.instance.empresa = _get_empresa_atual(self.request)
        messages.success(self.request, 'Tipo de papel cadastrado com sucesso.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = 'Novo tipo de papel'
        ctx['cancel_url'] = reverse_lazy('pessoas:tipo_papel_list')
        return ctx


class TipoPapelUpdateView(LoginRequiredMixin, UpdateView):
    model = TipoPapel
    template_name = 'pessoas/config_form.html'
    fields = ['nome']
    success_url = reverse_lazy('pessoas:tipo_papel_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        messages.success(self.request, 'Tipo de papel atualizado.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = f'Editar: {self.object.nome}'
        ctx['cancel_url'] = reverse_lazy('pessoas:tipo_papel_list')
        return ctx


class TipoPapelDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk):
        obj = get_object_or_404(TipoPapel.objects, pk=pk)
        return render(request, 'pessoas/config_confirm_delete.html', {
            'object': obj,
            'titulo': 'Excluir tipo de papel',
            'cancel_url': reverse_lazy('pessoas:tipo_papel_list'),
        })

    def post(self, request, pk):
        obj = get_object_or_404(TipoPapel.objects, pk=pk)
        obj.soft_delete(user=request.user)
        messages.success(request, f'Tipo "{obj.nome}" excluído.')
        return redirect('pessoas:tipo_papel_list')


# ─── Pessoa ────────────────────────────────────────────────────────────────────

class PessoaForm(django_forms.ModelForm):
    class Meta:
        model = Pessoa
        fields = [
            'tipo',
            'nome', 'cpf', 'rg', 'data_nascimento', 'estado_civil', 'profissao', 'nacionalidade',
            'razao_social', 'nome_fantasia', 'cnpj', 'inscricao_estadual',
            'email', 'telefone', 'celular',
            'cep', 'logradouro', 'numero', 'complemento', 'bairro', 'cidade', 'estado',
            'observacoes', 'conjuge',
        ]
        widgets = {
            'data_nascimento': django_forms.DateInput(attrs={'type': 'date'}),
            'observacoes': django_forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            qs = Pessoa.objects.filter(empresa=empresa)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            self.fields['conjuge'].queryset = qs
        else:
            self.fields['conjuge'].queryset = Pessoa.objects.none()
        self.fields['conjuge'].required = False

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get('tipo')
        if tipo == Pessoa.PF and not cleaned.get('nome'):
            self.add_error('nome', 'Nome é obrigatório para Pessoa Física.')
        if tipo == Pessoa.PJ and not cleaned.get('razao_social'):
            self.add_error('razao_social', 'Razão Social é obrigatória para Pessoa Jurídica.')
        return cleaned


class PessoaListView(LoginRequiredMixin, EmpresaQuerysetMixin, ListView):
    model = Pessoa
    template_name = 'pessoas/pessoa_list.html'
    context_object_name = 'pessoas'
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related('papeis__papel')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(nome__icontains=q) | Q(razao_social__icontains=q) |
                Q(nome_fantasia__icontains=q) | Q(cpf__icontains=q) |
                Q(cnpj__icontains=q) | Q(email__icontains=q)
            )
        papel = self.request.GET.get('papel', '').strip()
        if papel:
            qs = qs.filter(papeis__papel_id=papel)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        ctx['papel_filtro'] = self.request.GET.get('papel', '')
        empresa = _get_empresa_atual(self.request)
        ctx['tipos_papel'] = TipoPapel.objects.filter(empresa=empresa) if empresa else TipoPapel.objects.none()
        return ctx


class PessoaDetailView(LoginRequiredMixin, DetailView):
    model = Pessoa
    template_name = 'pessoas/pessoa_detail.html'
    context_object_name = 'pessoa'

    def get_object(self):
        return get_object_or_404(Pessoa.all_objects, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['papeis'] = self.object.papeis.select_related('papel').all()
        ctx['representantes'] = self.object.representantes_legais.select_related('pessoa_fisica').all() \
            if self.object.tipo == Pessoa.PJ else []
        empresa = _get_empresa_atual(self.request)
        ctx['pessoas_pf'] = Pessoa.objects.filter(empresa=empresa, tipo=Pessoa.PF) if empresa else []
        papeis_ids = self.object.papeis.values_list('papel_id', flat=True)
        ctx['papeis_disponiveis'] = (
            TipoPapel.objects.filter(empresa=empresa).exclude(pk__in=papeis_ids)
            if empresa else TipoPapel.objects.none()
        )
        ctx['history_entries'] = _build_history(self.object)
        return ctx


def _get_tipos_papel(request):
    empresa = _get_empresa_atual(request)
    return TipoPapel.objects.filter(empresa=empresa) if empresa else TipoPapel.objects.none()


def _salvar_papeis(pessoa, papeis_ids):
    papeis_ids = set(int(p) for p in papeis_ids if p)
    atuais = set(pessoa.papeis.values_list('papel_id', flat=True))
    for pid in papeis_ids - atuais:
        PessoaPapel.objects.get_or_create(pessoa=pessoa, papel_id=pid)
    pessoa.papeis.filter(papel_id__in=atuais - papeis_ids).delete()


class PessoaCreateView(LoginRequiredMixin, CreateView):
    model = Pessoa
    form_class = PessoaForm
    template_name = 'pessoas/pessoa_form.html'

    def get_form(self, form_class=None):
        form = PessoaForm(**self.get_form_kwargs(), empresa=_get_empresa_atual(self.request))
        return _style_form(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['tipos_papel'] = _get_tipos_papel(self.request)
        ctx['papeis_selecionados'] = []
        return ctx

    def form_valid(self, form):
        form.instance.empresa = _get_empresa_atual(self.request)
        response = super().form_valid(form)
        _salvar_papeis(self.object, self.request.POST.getlist('papeis'))
        messages.success(self.request, 'Pessoa cadastrada com sucesso.')
        return response

    def get_success_url(self):
        return reverse_lazy('pessoas:pessoa_detail', kwargs={'pk': self.object.pk})


class PessoaUpdateView(LoginRequiredMixin, UpdateView):
    model = Pessoa
    form_class = PessoaForm
    template_name = 'pessoas/pessoa_form.html'

    def get_form(self, form_class=None):
        form = PessoaForm(**self.get_form_kwargs(), empresa=_get_empresa_atual(self.request))
        return _style_form(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['tipos_papel'] = _get_tipos_papel(self.request)
        ctx['papeis_selecionados'] = list(self.object.papeis.values_list('papel_id', flat=True))
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        _salvar_papeis(self.object, self.request.POST.getlist('papeis'))
        messages.success(self.request, 'Pessoa atualizada com sucesso.')
        return response

    def get_success_url(self):
        return reverse_lazy('pessoas:pessoa_detail', kwargs={'pk': self.object.pk})


class PessoaDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk):
        obj = get_object_or_404(Pessoa.objects, pk=pk)
        return render(request, 'pessoas/pessoa_confirm_delete.html', {'pessoa': obj})

    def post(self, request, pk):
        obj = get_object_or_404(Pessoa.objects, pk=pk)
        obj.soft_delete(user=request.user)
        messages.success(request, f'"{obj.nome_exibicao}" excluído(a).')
        return redirect('pessoas:pessoa_list')


class PessoaRestoreView(LoginRequiredMixin, View):
    def post(self, request, pk):
        obj = get_object_or_404(Pessoa.all_objects, pk=pk, deletado_em__isnull=False)
        obj.restaurar()
        messages.success(request, f'"{obj.nome_exibicao}" restaurado(a).')
        return redirect('pessoas:pessoa_detail', pk=obj.pk)


@login_required
def representante_add(request, pk):
    pj = get_object_or_404(Pessoa.objects, pk=pk, tipo=Pessoa.PJ)
    if request.method == 'POST':
        pf_id = request.POST.get('pessoa_id')
        cargo = request.POST.get('cargo', '').strip()
        if pf_id:
            pf = get_object_or_404(Pessoa.objects, pk=pf_id, tipo=Pessoa.PF)
            RepresentanteLegal.objects.get_or_create(
                pessoa_juridica=pj, pessoa_fisica=pf,
                defaults={'cargo': cargo},
            )
            messages.success(request, f'{pf.nome_exibicao} adicionado como representante legal.')
    return redirect('pessoas:pessoa_detail', pk=pk)


@login_required
def representante_remove(request, pk, rep_pk):
    pj = get_object_or_404(Pessoa.objects, pk=pk, tipo=Pessoa.PJ)
    if request.method == 'POST':
        RepresentanteLegal.objects.filter(pk=rep_pk, pessoa_juridica=pj).delete()
        messages.success(request, 'Representante removido.')
    return redirect('pessoas:pessoa_detail', pk=pk)


@login_required
def papel_add(request, pk):
    pessoa = get_object_or_404(Pessoa.objects, pk=pk)
    if request.method == 'POST':
        papel_id = request.POST.get('papel_id')
        papel = get_object_or_404(TipoPapel.objects, pk=papel_id)
        PessoaPapel.objects.get_or_create(pessoa=pessoa, papel=papel)
        messages.success(request, f'Papel "{papel.nome}" adicionado.')
    return redirect('pessoas:pessoa_detail', pk=pk)


@login_required
def papel_remove(request, pk, papel_pk):
    pessoa = get_object_or_404(Pessoa.objects, pk=pk)
    if request.method == 'POST':
        PessoaPapel.objects.filter(pessoa=pessoa, pk=papel_pk).delete()
        messages.success(request, 'Papel removido.')
    return redirect('pessoas:pessoa_detail', pk=pk)


@login_required
def tipo_papel_lista_pdf(request):
    empresa = _get_empresa_atual(request)
    qs = TipoPapel.objects.filter(empresa=empresa) if empresa else TipoPapel.objects.none()
    return render_to_pdf(
        'pessoas/tipo_papel_lista_pdf.html',
        {'tipos': qs},
        filename='tipos-de-papel.pdf',
    )


@login_required
def pessoa_pdf(request, pk):
    pessoa = get_object_or_404(
        Pessoa.all_objects.prefetch_related('papeis__papel'), pk=pk
    )
    return render_to_pdf(
        'pessoas/pessoa_pdf.html',
        {'pessoa': pessoa},
        filename=f'pessoa-{pessoa.nome_exibicao}.pdf',
    )


@login_required
def pessoa_lista_pdf(request):
    empresa = _get_empresa_atual(request)
    q = request.GET.get('q', '').strip()
    papel = request.GET.get('papel', '').strip()
    qs = (
        Pessoa.objects.filter(empresa=empresa).prefetch_related('papeis__papel')
        if empresa else Pessoa.objects.none()
    )
    if q:
        qs = qs.filter(
            Q(nome__icontains=q) | Q(razao_social__icontains=q) |
            Q(nome_fantasia__icontains=q) | Q(cpf__icontains=q) | Q(cnpj__icontains=q)
        )
    if papel:
        qs = qs.filter(papeis__papel_id=papel)
    return render_to_pdf(
        'pessoas/pessoa_lista_pdf.html',
        {'pessoas': qs, 'q': q},
        filename='pessoas.pdf',
    )
