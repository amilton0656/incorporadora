from decimal import Decimal

from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.core.pdf import render_to_pdf
from apps.empreendimentos.models import Empreendimento, Unidade
from .models import TabelaVendas, TabelaVendasItem

_INPUT = (
    'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm '
    'focus:outline-none focus:ring-2 focus:ring-brand focus:border-transparent transition'
)
_INPUT_ERR = _INPUT.replace('border-gray-300', 'border-red-400')
_SELECT = _INPUT + ' bg-white'
_CHECKBOX = 'w-4 h-4 text-brand border-gray-300 rounded focus:ring-brand'


def _style_form(form):
    for fname, field in form.fields.items():
        has_error = form.is_bound and fname in form.errors
        widget = field.widget
        if isinstance(widget, (django_forms.Select, django_forms.SelectMultiple)):
            widget.attrs['class'] = (_INPUT_ERR if has_error else _INPUT).replace('', '') + ' bg-white'
        elif isinstance(widget, django_forms.CheckboxInput):
            widget.attrs['class'] = _CHECKBOX
        elif isinstance(widget, django_forms.Textarea):
            widget.attrs['class'] = _INPUT_ERR if has_error else _INPUT
        else:
            widget.attrs['class'] = _INPUT_ERR if has_error else _INPUT
    return form


def _get_empreendimento(pk):
    return get_object_or_404(Empreendimento.all_objects, pk=pk)


def _unidades_principais(empreendimento, modo):
    qs = Unidade.objects.filter(
        bloco__empreendimento=empreendimento,
        unidade_principal__isnull=True,
        deletado_em__isnull=True,
    ).select_related('status', 'tipo').order_by('bloco__ordem', 'ordem', 'numero')
    if modo == 'disponiveis':
        qs = qs.filter(
            Q(status__nome__icontains='disponív') | Q(status__isnull=True)
        )
    return qs


# ─── Forms ────────────────────────────────────────────────────────────────────

class TabelaVendasForm(django_forms.ModelForm):
    MODO_CHOICES = [
        ('todas', 'Todas as unidades principais'),
        ('disponiveis', 'Apenas unidades disponíveis'),
    ]
    modo_importacao = django_forms.ChoiceField(
        choices=MODO_CHOICES,
        label='Importar unidades',
        initial='todas',
    )

    class Meta:
        model = TabelaVendas
        fields = ['nome', 'vigencia_inicio', 'vigencia_fim', 'ativa', 'observacoes']
        widgets = {
            'vigencia_inicio': django_forms.DateInput(attrs={'type': 'date'}),
            'vigencia_fim': django_forms.DateInput(attrs={'type': 'date'}),
            'observacoes': django_forms.Textarea(attrs={'rows': 2}),
        }


class TabelaVendasEditForm(django_forms.ModelForm):
    class Meta:
        model = TabelaVendas
        fields = ['nome', 'vigencia_inicio', 'vigencia_fim', 'ativa', 'observacoes']
        widgets = {
            'vigencia_inicio': django_forms.DateInput(attrs={'type': 'date'}),
            'vigencia_fim': django_forms.DateInput(attrs={'type': 'date'}),
            'observacoes': django_forms.Textarea(attrs={'rows': 2}),
        }


class TabelaVendasItemForm(django_forms.ModelForm):
    class Meta:
        model = TabelaVendasItem
        fields = [
            'ato_qtd', 'ato_valor',
            'parcelas_mensais_qtd', 'parcelas_mensais_valor',
            'reforcos_qtd', 'reforcos_valor',
            'chaves_valor', 'financiamento_valor',
        ]


# ─── Tabela de Vendas ─────────────────────────────────────────────────────────

class TabelaVendasListView(LoginRequiredMixin, ListView):
    model = TabelaVendas
    template_name = 'vendas/tabela_list.html'
    context_object_name = 'tabelas'

    def get_queryset(self):
        self.empreendimento = _get_empreendimento(self.kwargs['pk'])
        return TabelaVendas.all_objects.filter(
            empreendimento=self.empreendimento
        ).prefetch_related('itens')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empreendimento'] = self.empreendimento
        return ctx


class TabelaVendasDetailView(LoginRequiredMixin, DetailView):
    model = TabelaVendas
    template_name = 'vendas/tabela_detail.html'
    context_object_name = 'tabela'
    pk_url_kwarg = 'tabela_pk'

    def get_object(self):
        self.empreendimento = _get_empreendimento(self.kwargs['pk'])
        return get_object_or_404(
            TabelaVendas.all_objects,
            pk=self.kwargs['tabela_pk'],
            empreendimento=self.empreendimento,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empreendimento'] = self.empreendimento
        itens = self.object.itens.select_related(
            'unidade__status', 'unidade__tipo', 'unidade__bloco'
        ).prefetch_related('unidade__designacoes', 'unidade__complementares__status')
        ctx['itens'] = itens
        ctx['total_geral'] = sum((i.valor_total for i in itens), Decimal('0'))
        return ctx


class TabelaVendasCreateView(LoginRequiredMixin, CreateView):
    model = TabelaVendas
    form_class = TabelaVendasForm
    template_name = 'vendas/tabela_form.html'

    def get_empreendimento(self):
        if not hasattr(self, '_empreendimento'):
            self._empreendimento = _get_empreendimento(self.kwargs['pk'])
        return self._empreendimento

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empreendimento'] = self.get_empreendimento()
        return ctx

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        emp = self.get_empreendimento()
        form.instance.empreendimento = emp
        response = super().form_valid(form)

        modo = form.cleaned_data['modo_importacao']
        unidades = _unidades_principais(emp, modo)
        itens = [TabelaVendasItem(tabela=self.object, unidade=u) for u in unidades]
        TabelaVendasItem.objects.bulk_create(itens)

        messages.success(self.request, f'Tabela criada com {len(itens)} unidade(s).')
        return response

    def get_success_url(self):
        return reverse_lazy('vendas:tabela_detail', kwargs={
            'pk': self.kwargs['pk'], 'tabela_pk': self.object.pk
        })


class TabelaVendasUpdateView(LoginRequiredMixin, UpdateView):
    model = TabelaVendas
    form_class = TabelaVendasEditForm
    template_name = 'vendas/tabela_edit_form.html'
    pk_url_kwarg = 'tabela_pk'

    def get_object(self):
        self.empreendimento = _get_empreendimento(self.kwargs['pk'])
        return get_object_or_404(
            TabelaVendas.objects, pk=self.kwargs['tabela_pk'],
            empreendimento=self.empreendimento,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empreendimento'] = self.empreendimento
        return ctx

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        messages.success(self.request, 'Tabela atualizada.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('vendas:tabela_detail', kwargs={
            'pk': self.kwargs['pk'], 'tabela_pk': self.object.pk
        })


class TabelaVendasDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk, tabela_pk):
        empreendimento = _get_empreendimento(pk)
        tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)
        return render(request, 'vendas/tabela_confirm_delete.html', {
            'tabela': tabela, 'empreendimento': empreendimento
        })

    def post(self, request, pk, tabela_pk):
        empreendimento = _get_empreendimento(pk)
        tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)
        tabela.soft_delete(user=request.user)
        messages.success(request, f'Tabela "{tabela.nome}" excluída.')
        return redirect('vendas:tabela_list', pk=pk)


# ─── Item ─────────────────────────────────────────────────────────────────────

class TabelaVendasItemUpdateView(LoginRequiredMixin, UpdateView):
    model = TabelaVendasItem
    form_class = TabelaVendasItemForm
    template_name = 'vendas/tabela_item_form.html'
    pk_url_kwarg = 'item_pk'

    def get_object(self):
        self.empreendimento = _get_empreendimento(self.kwargs['pk'])
        self.tabela = get_object_or_404(
            TabelaVendas.objects, pk=self.kwargs['tabela_pk'],
            empreendimento=self.empreendimento,
        )
        return get_object_or_404(TabelaVendasItem, pk=self.kwargs['item_pk'], tabela=self.tabela)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empreendimento'] = self.empreendimento
        ctx['tabela'] = self.tabela
        return ctx

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        messages.success(self.request, 'Item atualizado.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('vendas:tabela_detail', kwargs={
            'pk': self.kwargs['pk'], 'tabela_pk': self.tabela.pk
        })


# ─── PDF ──────────────────────────────────────────────────────────────────────

@login_required
def tabela_pdf(request, pk, tabela_pk):
    empreendimento = _get_empreendimento(pk)
    tabela = get_object_or_404(
        TabelaVendas.all_objects, pk=tabela_pk, empreendimento=empreendimento
    )
    itens = tabela.itens.select_related(
        'unidade__status', 'unidade__tipo', 'unidade__bloco'
    ).prefetch_related('unidade__designacoes', 'unidade__complementares')

    total_geral = sum((i.valor_total for i in itens), Decimal('0'))

    return render_to_pdf('vendas/tabela_pdf.html', {
        'empreendimento': empreendimento,
        'tabela': tabela,
        'itens': itens,
        'total_geral': total_geral,
    }, filename=f'tabela-{tabela.nome}.pdf')
