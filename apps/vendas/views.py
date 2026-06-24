from decimal import Decimal, InvalidOperation

from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.core.pdf import render_to_pdf
from apps.empreendimentos.models import Empreendimento, Unidade
from .models import TabelaSerie, TabelaVendas, TabelaVendasItem, TabelaVendasItemValor

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
            widget.attrs['class'] = (_INPUT_ERR if has_error else _INPUT) + ' bg-white'
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
    ).exclude(
        tipo__categoria='complementar'  # exclui garagens/HBs sem vínculo cadastrado
    ).select_related('status', 'tipo').order_by('bloco__ordem', 'ordem', 'numero')
    if modo == 'disponiveis':
        qs = qs.filter(
            Q(status__nome__icontains='disponív') | Q(status__isnull=True)
        )
    return qs


def _parse_currency(raw):
    try:
        clean = raw.replace('R$', '').replace('.', '').replace(',', '.').strip()
        return Decimal(clean or '0')
    except (InvalidOperation, AttributeError):
        return Decimal('0')


# ─── Forms ────────────────────────────────────────────────────────────────────

class TabelaVendasForm(django_forms.ModelForm):
    MODO_CHOICES = [
        ('todas', 'Todas as unidades principais'),
        ('disponiveis', 'Apenas unidades disponíveis'),
    ]
    modo_importacao = django_forms.ChoiceField(
        choices=MODO_CHOICES, label='Importar unidades', initial='todas',
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


class TabelaSerieForm(django_forms.ModelForm):
    class Meta:
        model = TabelaSerie
        fields = ['tipo', 'percentual', 'quantidade', 'data_primeiro_vencimento', 'periodicidade']
        widgets = {
            'data_primeiro_vencimento': django_forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('quantidade') == 1:
            cleaned['periodicidade'] = ''
        return cleaned


# ─── Tabela de Vendas ─────────────────────────────────────────────────────────

class TabelaVendasListView(LoginRequiredMixin, ListView):
    model = TabelaVendas
    template_name = 'vendas/tabela_list.html'
    context_object_name = 'tabelas'

    def get_queryset(self):
        self.empreendimento = _get_empreendimento(self.kwargs['pk'])
        return TabelaVendas.all_objects.filter(
            empreendimento=self.empreendimento
        ).prefetch_related('itens', 'series')

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

        series = list(self.object.series.all())
        ctx['series'] = series

        # Tipos disponíveis para adicionar (ainda não configurados)
        tipos_usados = {s.tipo for s in series}
        ctx['tipos_disponiveis'] = [
            (k, v) for k, v in TabelaSerie.TIPO_CHOICES if k not in tipos_usados
        ]

        itens = list(
            self.object.itens
            .select_related('unidade__status', 'unidade__tipo', 'unidade__bloco')
            .prefetch_related(
                'unidade__designacoes',
                'unidade__complementares__tipo',
                'valores__serie',
            )
        )

        # Monta estrutura: [{item, valores_ordenados: [ItemValor|None, ...]}, ...]
        itens_data = []
        total_geral      = Decimal('0')
        total_area_priv  = Decimal('0')
        total_area_tot   = Decimal('0')
        totais_series    = [Decimal('0')] * len(series)

        for item in itens:
            valores_dict = {v.serie_id: v for v in item.valores.all()}
            valores_ordenados = [valores_dict.get(s.pk) for s in series]
            item_total = sum(
                (v.valor_total for v in valores_dict.values()), Decimal('0')
            )
            total_geral     += item_total
            total_area_priv += item.unidade.area_privativa or Decimal('0')
            total_area_tot  += item.unidade.area_total or Decimal('0')
            for i, v in enumerate(valores_ordenados):
                if v:
                    totais_series[i] += v.valor_total
            itens_data.append({
                'item': item,
                'valores': valores_ordenados,
                'total': item_total,
            })

        ctx['itens_data']    = itens_data
        ctx['total_geral']   = total_geral
        ctx['total_area_priv'] = total_area_priv
        ctx['total_area_tot']  = total_area_tot
        ctx['totais_series']   = totais_series
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
        TabelaVendasItem.objects.bulk_create([
            TabelaVendasItem(tabela=self.object, unidade=u) for u in unidades
        ])

        messages.success(self.request, f'Tabela criada com {unidades.count()} unidade(s). Configure as séries para definir as colunas.')
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


# ─── Série ────────────────────────────────────────────────────────────────────

class TabelaSerieCreateView(LoginRequiredMixin, View):
    def get(self, request, pk, tabela_pk):
        empreendimento = _get_empreendimento(pk)
        tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)
        form = _style_form(TabelaSerieForm())
        # Exclude already-used tipos
        tipos_usados = set(tabela.series.values_list('tipo', flat=True))
        form.fields['tipo'].choices = [
            (k, v) for k, v in TabelaSerie.TIPO_CHOICES if k not in tipos_usados
        ]
        return render(request, 'vendas/tabela_serie_form.html', {
            'empreendimento': empreendimento, 'tabela': tabela, 'form': form,
        })

    def post(self, request, pk, tabela_pk):
        empreendimento = _get_empreendimento(pk)
        tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)
        tipos_usados = set(tabela.series.values_list('tipo', flat=True))
        form = _style_form(TabelaSerieForm(request.POST))
        form.fields['tipo'].choices = [
            (k, v) for k, v in TabelaSerie.TIPO_CHOICES if k not in tipos_usados
        ]

        if form.is_valid():
            serie = form.save(commit=False)
            serie.tabela = tabela
            serie.save()
            # Cria ItemValor zerado para todos os itens existentes
            itens = list(tabela.itens.all())
            TabelaVendasItemValor.objects.bulk_create([
                TabelaVendasItemValor(item=item, serie=serie, valor=Decimal('0'))
                for item in itens
            ])
            messages.success(request, f'Série "{serie.get_tipo_display()}" adicionada.')
            return redirect('vendas:tabela_detail', pk=pk, tabela_pk=tabela_pk)

        return render(request, 'vendas/tabela_serie_form.html', {
            'empreendimento': empreendimento, 'tabela': tabela, 'form': form,
        })


class TabelaSerieUpdateView(LoginRequiredMixin, View):
    def _get_objects(self, pk, tabela_pk, serie_pk):
        empreendimento = _get_empreendimento(pk)
        tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)
        serie = get_object_or_404(TabelaSerie, pk=serie_pk, tabela=tabela)
        return empreendimento, tabela, serie

    def get(self, request, pk, tabela_pk, serie_pk):
        empreendimento, tabela, serie = self._get_objects(pk, tabela_pk, serie_pk)
        form = TabelaSerieForm(instance=serie)
        form.fields['tipo'].disabled = True
        form = _style_form(form)
        return render(request, 'vendas/tabela_serie_form.html', {
            'empreendimento': empreendimento, 'tabela': tabela, 'form': form,
            'serie': serie, 'editando': True,
        })

    def post(self, request, pk, tabela_pk, serie_pk):
        empreendimento, tabela, serie = self._get_objects(pk, tabela_pk, serie_pk)
        form = TabelaSerieForm(request.POST, instance=serie)
        form.fields['tipo'].disabled = True
        form = _style_form(form)
        if form.is_valid():
            form.save()
            messages.success(request, f'Série "{serie.get_tipo_display()}" atualizada.')
            return redirect('vendas:tabela_detail', pk=pk, tabela_pk=tabela_pk)
        return render(request, 'vendas/tabela_serie_form.html', {
            'empreendimento': empreendimento, 'tabela': tabela, 'form': form,
            'serie': serie, 'editando': True,
        })


class TabelaLimparComplementaresView(LoginRequiredMixin, View):
    def post(self, request, pk, tabela_pk):
        empreendimento = _get_empreendimento(pk)
        tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)
        removidos = tabela.itens.filter(
            unidade__tipo__categoria='complementar'
        ).delete()[0]
        messages.success(request, f'{removidos} item(ns) indevido(s) removido(s).')
        return redirect('vendas:tabela_detail', pk=pk, tabela_pk=tabela_pk)


class TabelaSerieDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk, tabela_pk, serie_pk):
        empreendimento = _get_empreendimento(pk)
        tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)
        serie = get_object_or_404(TabelaSerie, pk=serie_pk, tabela=tabela)
        nome = serie.get_tipo_display()
        serie.delete()
        messages.success(request, f'Série "{nome}" removida.')
        return redirect('vendas:tabela_detail', pk=pk, tabela_pk=tabela_pk)


# ─── Item (edição de valores) ─────────────────────────────────────────────────

class TabelaVendasItemUpdateView(LoginRequiredMixin, View):
    def _get_objects(self, pk, tabela_pk, item_pk):
        empreendimento = _get_empreendimento(pk)
        tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)
        item = get_object_or_404(TabelaVendasItem, pk=item_pk, tabela=tabela)
        series = list(tabela.series.all())
        return empreendimento, tabela, item, series

    def get(self, request, pk, tabela_pk, item_pk):
        empreendimento, tabela, item, series = self._get_objects(pk, tabela_pk, item_pk)
        valores_dict = {v.serie_id: v for v in item.valores.select_related('serie').all()}
        series_valores = []
        for serie in series:
            valor_obj = valores_dict.get(serie.pk)
            if not valor_obj:
                valor_obj = TabelaVendasItemValor(item=item, serie=serie, valor=Decimal('0'))
            series_valores.append((serie, valor_obj))

        return render(request, 'vendas/tabela_item_form.html', {
            'empreendimento': empreendimento,
            'tabela': tabela,
            'item': item,
            'series_valores': series_valores,
        })

    def post(self, request, pk, tabela_pk, item_pk):
        empreendimento, tabela, item, series = self._get_objects(pk, tabela_pk, item_pk)
        for serie in series:
            raw = request.POST.get(f'valor_{serie.pk}', '0')
            valor = _parse_currency(raw)
            TabelaVendasItemValor.objects.update_or_create(
                item=item, serie=serie,
                defaults={'valor': valor},
            )
        messages.success(request, f'Valores de {item.unidade.numero} atualizados.')
        return redirect('vendas:tabela_detail', pk=pk, tabela_pk=tabela_pk)


# ─── Importação CSV ───────────────────────────────────────────────────────────

def _recalcular_item(item, series):
    """Recalcula os valores de todas as séries de um item com base em unidade.valor_tabela."""
    total = item.unidade.valor_tabela or Decimal('0')
    for serie in series:
        valor_parcela = serie.calcular_valor_parcela(total)
        TabelaVendasItemValor.objects.update_or_create(
            item=item, serie=serie,
            defaults={'valor': valor_parcela},
        )


@login_required
def tabela_modelo_csv(request, pk, tabela_pk):
    """Download do modelo CSV: unidade + valor_total + situacao."""
    import csv as csv_module
    empreendimento = _get_empreendimento(pk)
    tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="modelo-{tabela.nome}.csv"'

    writer = csv_module.writer(response, delimiter=';')
    writer.writerow(['UNIDADE', 'VALOR TOTAL', 'SITUAÇÃO'])

    for item in tabela.itens.select_related('unidade__status'):
        valor = item.unidade.valor_tabela or Decimal('0')
        situacao = item.unidade.status.nome if item.unidade.status else ''
        writer.writerow([item.unidade.numero, str(valor).replace('.', ','), situacao])

    return response


@login_required
def tabela_importar_csv(request, pk, tabela_pk):
    empreendimento = _get_empreendimento(pk)
    tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)
    series = list(tabela.series.all())

    # Aviso se percentuais não somam 100
    soma_pct = sum(s.percentual for s in series)

    if request.method == 'GET':
        return render(request, 'vendas/tabela_importar_csv.html', {
            'empreendimento': empreendimento,
            'tabela': tabela,
            'series': series,
            'soma_pct': soma_pct,
        })

    arquivo = request.FILES.get('arquivo')
    if not arquivo:
        messages.error(request, 'Selecione um arquivo CSV.')
        return redirect('vendas:tabela_importar_csv', pk=pk, tabela_pk=tabela_pk)

    import csv as csv_module
    import io

    try:
        raw = arquivo.read()
        try:
            texto = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            texto = raw.decode('latin-1')

        reader = csv_module.DictReader(io.StringIO(texto), delimiter=';')
        # Normaliza nomes de colunas para busca case-insensitive
        fieldnames_norm = {f.strip().upper(): f for f in (reader.fieldnames or [])}

        col_unidade    = fieldnames_norm.get('UNIDADE')
        col_valor      = fieldnames_norm.get('VALOR TOTAL')
        col_situacao   = fieldnames_norm.get('SITUAÇÃO') or fieldnames_norm.get('SITUACAO')

        if not col_unidade or not col_valor:
            messages.error(request, 'O arquivo deve ter as colunas "UNIDADE" e "VALOR TOTAL".')
            return redirect('vendas:tabela_importar_csv', pk=pk, tabela_pk=tabela_pk)

        tem_situacao = bool(col_situacao)

        from apps.empreendimentos.models import Unidade as UnidadeModel, StatusUnidade

        # Mapeia numero e nome_exibicao → unidade (para lookup flexível)
        unidades_tabela = list(
            UnidadeModel.objects.filter(
                tabela_itens__tabela=tabela
            ).select_related('status')
        )
        unidade_por_numero = {}
        for u in unidades_tabela:
            unidade_por_numero[u.numero.strip()] = u
            if u.nome_exibicao:
                unidade_por_numero[u.nome_exibicao.strip()] = u

        # Mapeia numero → TabelaVendasItem
        item_por_unidade_id = {
            item.unidade_id: item
            for item in tabela.itens.all()
        }

        # Mapeia nome de status → StatusUnidade (da empresa do empreendimento)
        status_por_nome = {
            s.nome.strip().lower(): s
            for s in StatusUnidade.objects.filter(empresa=empreendimento.empresa)
        }

        atualizados = 0
        ignorados = 0

        for linha in reader:
            numero = (linha.get(col_unidade) or '').strip()
            unidade = unidade_por_numero.get(numero)
            if not unidade:
                ignorados += 1
                continue

            item = item_por_unidade_id.get(unidade.pk)
            if not item:
                ignorados += 1
                continue

            # Atualiza valor_tabela — trata R$, separadores de milhar e decimal BR
            valor_total = _parse_currency(linha.get(col_valor) or '0')

            campos_save = ['valor_tabela']
            unidade.valor_tabela = valor_total

            # Atualiza status se coluna presente
            if tem_situacao:
                nome_status = (linha.get(col_situacao) or '').strip().lower()
                status_obj = status_por_nome.get(nome_status)
                # Tenta variação masculino/feminino (ex: Vendida→Vendido, Bloqueada→Bloqueado)
                if not status_obj:
                    if nome_status.endswith('a'):
                        status_obj = status_por_nome.get(nome_status[:-1] + 'o')
                    elif nome_status.endswith('o'):
                        status_obj = status_por_nome.get(nome_status[:-1] + 'a')
                if status_obj:
                    unidade.status = status_obj
                    campos_save.append('status')

            unidade.save(update_fields=campos_save)

            # Recalcula valores das séries
            item.unidade = unidade
            _recalcular_item(item, series)
            atualizados += 1

        # Reaplica situações fixadas (pins) para as unidades atualizadas
        from apps.empreendimentos.models import SituacaoFixada
        pins = SituacaoFixada.objects.filter(
            unidade__in=[u.pk for u in unidades_tabela]
        ).select_related('unidade', 'status')
        pins_aplicados = 0
        for pin in pins:
            pin.unidade.status = pin.status
            pin.unidade.save(update_fields=['status'])
            pins_aplicados += 1

        msg = f'{atualizados} unidade(s) importada(s) e valores recalculados.'
        if pins_aplicados:
            msg += f' {pins_aplicados} situação(ões) fixada(s) reaplicada(s).'
        if ignorados:
            msg += f' {ignorados} linha(s) ignorada(s) (unidade não encontrada na tabela).'
        messages.success(request, msg)

    except Exception as e:
        messages.error(request, f'Erro ao processar o arquivo: {e}')

    return redirect('vendas:tabela_detail', pk=pk, tabela_pk=tabela_pk)


@login_required
def tabela_recalcular(request, pk, tabela_pk):
    """Recalcula todos os valores com base em Unidade.valor_tabela e percentuais das séries."""
    if request.method != 'POST':
        return redirect('vendas:tabela_detail', pk=pk, tabela_pk=tabela_pk)

    empreendimento = _get_empreendimento(pk)
    tabela = get_object_or_404(TabelaVendas.objects, pk=tabela_pk, empreendimento=empreendimento)
    series = list(tabela.series.all())
    itens = list(tabela.itens.select_related('unidade'))

    for item in itens:
        _recalcular_item(item, series)

    messages.success(request, f'Valores recalculados para {len(itens)} unidade(s).')
    return redirect('vendas:tabela_detail', pk=pk, tabela_pk=tabela_pk)


# ─── PDF ──────────────────────────────────────────────────────────────────────

@login_required
def tabela_pdf(request, pk, tabela_pk):
    from io import BytesIO
    from datetime import datetime
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors

    empreendimento = _get_empreendimento(pk)
    tabela = get_object_or_404(TabelaVendas.all_objects, pk=tabela_pk, empreendimento=empreendimento)
    series = list(tabela.series.all())
    itens = list(
        tabela.itens
        .select_related('unidade__status', 'unidade__tipo', 'unidade__bloco')
        .prefetch_related(
            'unidade__designacoes',
            'unidade__complementares__tipo',
            'valores__serie',
        )
    )

    # ── helpers ───────────────────────────────────────────────────────────────
    def fmt_brl(v):
        if not v:
            return '—'
        s = '{:,.2f}'.format(float(v))
        return s.replace(',', 'X').replace('.', ',').replace('X', '.')

    def fmt_area(v, d=2):
        if not v:
            return '—'
        s = ('{:,.' + str(d) + 'f}').format(float(v))
        return s.replace(',', 'X').replace('.', ',').replace('X', '.')

    def get_gar(u):
        if u.gars_tab_vendas:
            return u.gars_tab_vendas
        parts = [d.nome for d in u.designacoes.all() if d.tipo in ('garagem_carro', 'garagem_moto')]
        parts += [c.numero for c in u.complementares.all() if c.tipo and 'aragem' in c.tipo.nome]
        return ' '.join(parts) or '—'

    def get_hb(u):
        if u.hb_tab_vendas:
            return u.hb_tab_vendas
        parts = [d.nome for d in u.designacoes.all() if d.tipo == 'hobby_box']
        parts += [c.numero for c in u.complementares.all() if c.tipo and 'obby' in c.tipo.nome]
        return ' '.join(parts) or '—'

    # ── pré-processa dados ────────────────────────────────────────────────────
    itens_data = []
    total_geral = Decimal('0')
    for item in itens:
        vd = {v.serie_id: v for v in item.valores.all()}
        item_total = sum((v.valor_total for v in vd.values()), Decimal('0'))
        total_geral += item_total
        itens_data.append({'item': item, 'valores': [vd.get(s.pk) for s in series], 'total': item_total})

    # ── cores ─────────────────────────────────────────────────────────────────
    BRAND     = colors.HexColor('#1B3A6B')
    GRAY_ROW  = colors.HexColor('#f9fafb')
    GRAY_LINE = colors.HexColor('#e5e7eb')
    WHITE     = colors.white
    TEXT_GRAY = colors.HexColor('#6b7280')
    TEXT_LITE = colors.HexColor('#9ca3af')

    # ── larguras das colunas ──────────────────────────────────────────────────
    pw, ph  = landscape(A4)
    margin  = 10 * mm
    usable  = pw - 2 * margin                  # ~257 mm disponíveis

    # larguras fixas: unidade, tipologia, area_priv, area_tot, gar, hb, situacao
    FIXED = [20, 20, 14, 14, 20, 10, 17]
    fixed_sum = sum(FIXED) * mm          # 115 mm
    n = len(series)
    # sobra distribuída igualmente entre séries + coluna total
    flex_w = (usable - fixed_sum) / (n + 1) if (n + 1) else 20 * mm

    col_widths = [FIXED[0]*mm, FIXED[1]*mm, FIXED[2]*mm, FIXED[3]*mm,
                  FIXED[4]*mm, FIXED[5]*mm] + [flex_w]*n + [flex_w, FIXED[6]*mm]

    # ── linhas da tabela ──────────────────────────────────────────────────────
    hdr = ['Unidade', 'Tipologia', 'Área\nPriv.(m²)', 'Área\nTotal(m²)', 'Gar.', 'HB']
    for s in series:
        lbl = s.get_tipo_display()
        lbl += f'\n({s.quantidade}×{" " + s.get_periodicidade_display() if s.periodicidade else ""})'
        hdr.append(lbl)
    hdr += ['Total', 'Situação']

    rows = [hdr]
    for row in itens_data:
        u = row['item'].unidade
        r = [u.numero, u.tipologia or '—',
             fmt_area(u.area_privativa), fmt_area(u.area_total),
             get_gar(u), get_hb(u)]
        for v in row['valores']:
            r.append(fmt_brl(v.valor) if v and v.valor else '—')
        r.append(fmt_brl(row['total']))
        r.append(u.status.nome if u.status else '—')
        rows.append(r)

    label_span = 6 + n
    total_row  = ([f'Total Geral — {len(itens_data)} unidade(s)']
                  + [''] * (label_span - 1)
                  + [fmt_brl(total_geral), ''])
    rows.append(total_row)

    last_data = len(rows) - 2
    total_idx = len(rows) - 1

    # ── estilos ───────────────────────────────────────────────────────────────
    ts = TableStyle([
        ('BACKGROUND',     (0, 0),          (-1, 0),           BRAND),
        ('TEXTCOLOR',      (0, 0),          (-1, 0),           WHITE),
        ('FONTNAME',       (0, 0),          (-1, 0),           'Helvetica-Bold'),
        ('FONTSIZE',       (0, 0),          (-1, 0),           6),
        ('ALIGN',          (0, 0),          (-1, 0),           'LEFT'),    # padrão: esquerda
        ('ALIGN',          (2, 0),          (3, 0),            'RIGHT'),   # Área Priv. e Área Total
        ('ALIGN',          (6, 0),          (-2, 0),           'RIGHT'),   # séries + Total
        ('VALIGN',         (0, 0),          (-1, -1),          'MIDDLE'),
        ('FONTNAME',       (0, 1),          (-1, last_data),   'Helvetica'),
        ('FONTSIZE',       (0, 1),          (-1, last_data),   6.5),
        ('ALIGN',          (0, 1),          (-1, last_data),   'RIGHT'),
        ('ALIGN',          (0, 1),          (1, last_data),    'LEFT'),
        ('ALIGN',          (4, 1),          (5, last_data),    'LEFT'),
        ('ALIGN',          (-1, 1),         (-1, last_data),   'CENTER'),
        ('FONTNAME',       (0, 1),          (0, last_data),    'Helvetica-Bold'),
        ('TEXTCOLOR',      (-2, 1),         (-2, last_data),   BRAND),
        ('FONTNAME',       (-2, 1),         (-2, last_data),   'Helvetica-Bold'),
        ('ROWBACKGROUNDS', (0, 1),          (-1, last_data),   [WHITE, GRAY_ROW]),
        ('LINEBELOW',      (0, 0),          (-1, last_data),   0.3, GRAY_LINE),
        ('LINEBELOW',      (0, 0),          (-1, 0),           1, BRAND),
        ('BACKGROUND',     (0, total_idx),  (-1, total_idx),   BRAND),
        ('TEXTCOLOR',      (0, total_idx),  (-1, total_idx),   WHITE),
        ('FONTNAME',       (0, total_idx),  (-1, total_idx),   'Helvetica-Bold'),
        ('FONTSIZE',       (0, total_idx),  (-1, total_idx),   6.5),
        ('ALIGN',          (-2, total_idx), (-2, total_idx),   'RIGHT'),
        ('SPAN',           (0, total_idx),  (label_span-1, total_idx)),
        ('TOPPADDING',     (0, 0),          (-1, -1),          2),
        ('BOTTOMPADDING',  (0, 0),          (-1, -1),          2),
        ('LEFTPADDING',    (0, 0),          (-1, -1),          2),
        ('RIGHTPADDING',   (0, 0),          (-1, -1),          2),
    ])

    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(ts)

    # ── monta PDF ─────────────────────────────────────────────────────────────
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                            leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=margin)

    h1  = ParagraphStyle('h1',  fontName='Helvetica-Bold', fontSize=13, textColor=BRAND, spaceAfter=2)
    sub = ParagraphStyle('sub', fontName='Helvetica', fontSize=8, textColor=TEXT_GRAY, spaceAfter=4)
    ft  = ParagraphStyle('ft',  fontName='Helvetica', fontSize=6, textColor=TEXT_LITE)

    sub_parts = [empreendimento.nome, empreendimento.empresa.nome]
    if tabela.ativa:
        sub_parts.append('Ativa')
    if tabela.vigencia_inicio or tabela.vigencia_fim:
        vig = 'Vigência: '
        if tabela.vigencia_inicio:
            vig += tabela.vigencia_inicio.strftime('%d/%m/%Y')
        if tabela.vigencia_inicio and tabela.vigencia_fim:
            vig += ' a '
        if tabela.vigencia_fim:
            vig += tabela.vigencia_fim.strftime('%d/%m/%Y')
        sub_parts.append(vig)

    doc.build([
        Paragraph(tabela.nome, h1),
        Paragraph(' — '.join(sub_parts), sub),
        t,
        Spacer(1, 3 * mm),
        Paragraph(f'Gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")} — {tabela.nome}', ft),
    ])

    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="tabela-{tabela.nome}.pdf"'
    return response
