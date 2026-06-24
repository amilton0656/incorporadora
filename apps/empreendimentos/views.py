import csv
import io
from django.http import HttpResponse
from decimal import Decimal, InvalidOperation

from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from django.db.models import Q

from apps.core.mixins import EmpresaQuerysetMixin
from apps.core.models import Empresa
from apps.core.pdf import render_to_pdf
from .models import Bloco, DesignacaoUnidade, Empreendimento, StatusUnidade, TipoUnidade, Unidade

_TIPO_DESIGNACAO_LABEL = {
    'garagem carro': DesignacaoUnidade.GARAGEM_CARRO,
    'garagem moto': DesignacaoUnidade.GARAGEM_MOTO,
    'hobby box': DesignacaoUnidade.HOBBY_BOX,
}

_TIPO_DESIGNACAO_PREFIXO = {
    'HB': DesignacaoUnidade.HOBBY_BOX,
    'M': DesignacaoUnidade.GARAGEM_MOTO,
    'G': DesignacaoUnidade.GARAGEM_CARRO,
}


def _inferir_tipo_designacao(numero):
    upper = numero.upper()
    for prefixo, tipo in _TIPO_DESIGNACAO_PREFIXO.items():
        if upper.startswith(prefixo):
            return tipo
    return None


def _colunas_faltando(fieldnames, obrigatorias):
    presentes = set(fieldnames or [])
    return sorted(obrigatorias - presentes)


_COLUNAS_UNIDADES = {
    'Bloco', 'numero', 'ordem', 'adicionais', 'tipo', 'tipologia',
    'localizacao', 'area_privativa', 'area_privativa_acessoria',
    'area_comum', 'fracao_ideal', 'valor_tabela', 'status',
    'descricao1', 'descricao2', 'descricao3',
}
_COLUNAS_UNIDADES_OPCIONAIS = {'linha', 'descricao_linha', 'coluna', 'gars_tab_vendas', 'hb_tab_vendas'}

_COLUNAS_VINCULOS = {'tipo', 'principal', 'complementar'}


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


# ─── Empreendimento ────────────────────────────────────────────────────────────

class EmpreendimentoListView(LoginRequiredMixin, EmpresaQuerysetMixin, ListView):
    model = Empreendimento
    template_name = 'empreendimentos/empreendimento_list.html'
    context_object_name = 'empreendimentos'
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(nome__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        return ctx


class EmpreendimentoDetailView(LoginRequiredMixin, DetailView):
    model = Empreendimento
    template_name = 'empreendimentos/empreendimento_detail.html'
    context_object_name = 'empreendimento'

    def get_object(self):
        return get_object_or_404(Empreendimento.all_objects, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        from django.db.models import Sum
        ctx = super().get_context_data(**kwargs)
        ctx['blocos'] = self.object.blocos.all()
        ctx['history_entries'] = _build_history(self.object)

        unidades = Unidade.objects.filter(bloco__empreendimento=self.object)
        totais = unidades.aggregate(
            area_privativa=Sum('area_privativa'),
            area_privativa_acessoria=Sum('area_privativa_acessoria'),
            area_comum=Sum('area_comum'),
            vgv=Sum('valor_tabela'),
        )
        ap  = totais['area_privativa'] or 0
        apa = totais['area_privativa_acessoria'] or 0
        ac  = totais['area_comum'] or 0
        ctx['totais'] = {
            'area_privativa':            ap,
            'area_privativa_acessoria':  apa,
            'area_comum':                ac,
            'area_real_total':           ap + apa + ac,
            'vgv':                       totais['vgv'] or 0,
        }
        return ctx


class EmpreendimentoCreateView(LoginRequiredMixin, CreateView):
    model = Empreendimento
    template_name = 'empreendimentos/empreendimento_form.html'
    fields = ['nome', 'status']
    success_url = reverse_lazy('empreendimentos:empreendimento_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        form.instance.empresa = _get_empresa_atual(self.request)
        messages.success(self.request, 'Empreendimento cadastrado com sucesso.')
        return super().form_valid(form)


class EmpreendimentoUpdateView(LoginRequiredMixin, UpdateView):
    model = Empreendimento
    template_name = 'empreendimentos/empreendimento_form.html'
    fields = ['nome', 'status']

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def get_success_url(self):
        messages.success(self.request, 'Empreendimento atualizado com sucesso.')
        return reverse_lazy('empreendimentos:empreendimento_detail', kwargs={'pk': self.object.pk})


class EmpreendimentoDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk):
        obj = get_object_or_404(Empreendimento.objects, pk=pk)
        return render(request, 'empreendimentos/empreendimento_confirm_delete.html', {'object': obj})

    def post(self, request, pk):
        obj = get_object_or_404(Empreendimento.objects, pk=pk)
        obj.soft_delete(user=request.user)
        messages.success(request, f'Empreendimento "{obj.nome}" excluído.')
        return redirect('empreendimentos:empreendimento_list')


class EmpreendimentoRestoreView(LoginRequiredMixin, View):
    def post(self, request, pk):
        obj = get_object_or_404(Empreendimento.all_objects, pk=pk, deletado_em__isnull=False)
        obj.restaurar()
        messages.success(request, f'Empreendimento "{obj.nome}" restaurado.')
        return redirect('empreendimentos:empreendimento_detail', pk=obj.pk)


class EmpreendimentoVinculosView(LoginRequiredMixin, DetailView):
    model = Empreendimento
    template_name = 'empreendimentos/empreendimento_vinculos.html'
    context_object_name = 'empreendimento'

    def get_object(self):
        return get_object_or_404(Empreendimento.all_objects, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        unidades_qs = (
            Unidade.objects
            .select_related('status', 'tipo', 'unidade_principal')
            .prefetch_related(
                Prefetch('complementares', queryset=Unidade.objects.select_related('status', 'tipo').order_by('ordem', 'numero')),
                'designacoes',
            )
            .order_by('ordem', 'numero')
        )

        blocos = self.object.blocos.prefetch_related(
            Prefetch('unidades', queryset=unidades_qs)
        ).all()

        blocos_dados = []
        for bloco in blocos:
            unidades = list(bloco.unidades.all())
            principais = [u for u in unidades if u.unidade_principal_id is None]
            sem_vinculo = [u for u in unidades if u.unidade_principal_id is not None and u.complementares.count() == 0]
            total_vinculos = sum(u.complementares.count() for u in principais)
            blocos_dados.append({
                'bloco': bloco,
                'principais': principais,
                'sem_vinculo_count': len([u for u in unidades if u.unidade_principal_id is not None]),
                'total_vinculos': total_vinculos,
            })

        ctx['blocos_dados'] = blocos_dados
        return ctx


class EmpreendimentoUnidadesListView(LoginRequiredMixin, DetailView):
    model = Empreendimento
    template_name = 'empreendimentos/empreendimento_unidades.html'
    context_object_name = 'empreendimento'

    def get_object(self):
        return get_object_or_404(Empreendimento.all_objects, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        from django.db.models import Sum
        ctx = super().get_context_data(**kwargs)

        unidades_qs = Unidade.objects.select_related('status', 'tipo').order_by('ordem', 'numero')
        blocos = list(self.object.blocos.prefetch_related(
            Prefetch('unidades', queryset=unidades_qs)
        ).all())

        def _totais(qs):
            t = qs.aggregate(
                ap=Sum('area_privativa'),
                apa=Sum('area_privativa_acessoria'),
                ac=Sum('area_comum'),
                fi=Sum('fracao_ideal'),
                vgv=Sum('valor_tabela'),
            )
            ap  = t['ap']  or 0
            apa = t['apa'] or 0
            ac  = t['ac']  or 0
            return {
                'area_privativa':           ap,
                'area_privativa_acessoria': apa,
                'area_comum':               ac,
                'area_real_total':          ap + apa + ac,
                'fracao_ideal':             t['fi']  or 0,
                'vgv':                      t['vgv'] or 0,
            }

        blocos_dados = []
        for bloco in blocos:
            qs = Unidade.objects.filter(bloco=bloco)
            blocos_dados.append({
                'bloco': bloco,
                'unidades': list(bloco.unidades.all()),
                'totais': _totais(qs),
            })

        ctx['blocos_dados'] = blocos_dados
        ctx['totais_gerais'] = _totais(Unidade.objects.filter(bloco__empreendimento=self.object))
        return ctx


@login_required
def empreendimento_lista_pdf(request):
    empresa = _get_empresa_atual(request)
    q = request.GET.get('q', '').strip()
    qs = Empreendimento.objects.filter(empresa=empresa) if empresa else Empreendimento.objects.none()
    if q:
        qs = qs.filter(nome__icontains=q)
    return render_to_pdf('empreendimentos/empreendimento_lista_pdf.html', {'empreendimentos': qs, 'q': q}, filename='empreendimentos.pdf')


@login_required
def empreendimento_pdf(request, pk):
    from django.db.models import Sum
    obj = get_object_or_404(Empreendimento.all_objects, pk=pk)
    unidades_qs = Unidade.objects.select_related('status', 'tipo').order_by('ordem', 'numero')
    blocos = list(obj.blocos.prefetch_related(
        Prefetch('unidades', queryset=unidades_qs)
    ).all())

    def _totais(qs):
        t = qs.aggregate(
            ap=Sum('area_privativa'),
            apa=Sum('area_privativa_acessoria'),
            ac=Sum('area_comum'),
            fi=Sum('fracao_ideal'),
            vgv=Sum('valor_tabela'),
        )
        ap  = t['ap']  or 0
        apa = t['apa'] or 0
        ac  = t['ac']  or 0
        return {
            'area_privativa':           ap,
            'area_privativa_acessoria': apa,
            'area_comum':               ac,
            'area_total':               ap + apa + ac,
            'fracao_ideal':             t['fi']  or 0,
            'vgv':                      t['vgv'] or 0,
        }

    blocos_dados = []
    for bloco in blocos:
        qs = Unidade.objects.filter(bloco=bloco)
        blocos_dados.append({'bloco': bloco, 'totais': _totais(qs)})

    totais_gerais = _totais(Unidade.objects.filter(bloco__empreendimento=obj))

    return render_to_pdf('empreendimentos/empreendimento_pdf.html', {
        'empreendimento': obj,
        'blocos_dados': blocos_dados,
        'totais_gerais': totais_gerais,
    }, filename=f'empreendimento-{obj.nome}.pdf')


# ─── Bloco ─────────────────────────────────────────────────────────────────────

@login_required
def empreendimento_vinculos_pdf(request, pk):
    empreendimento = get_object_or_404(Empreendimento.all_objects, pk=pk)

    unidades_qs = (
        Unidade.objects
        .select_related('status', 'tipo', 'unidade_principal')
        .prefetch_related(
            Prefetch('complementares', queryset=Unidade.objects.select_related('status', 'tipo').order_by('ordem', 'numero')),
            'designacoes',
        )
        .order_by('ordem', 'numero')
    )

    blocos = empreendimento.blocos.prefetch_related(
        Prefetch('unidades', queryset=unidades_qs)
    ).all()

    blocos_dados = []
    for bloco in blocos:
        unidades = list(bloco.unidades.all())
        principais = [u for u in unidades if u.unidade_principal_id is None]
        blocos_dados.append({'bloco': bloco, 'principais': principais})

    return render_to_pdf('empreendimentos/empreendimento_vinculos_pdf.html', {
        'empreendimento': empreendimento,
        'blocos_dados': blocos_dados,
    }, filename=f'vinculos-{empreendimento.nome}.pdf')


@login_required
def bloco_pdf(request, pk, bloco_pk):
    from django.db.models import Sum
    empreendimento = get_object_or_404(Empreendimento.all_objects, pk=pk)
    bloco = get_object_or_404(Bloco.all_objects, pk=bloco_pk, empreendimento=empreendimento)
    unidades = bloco.unidades.select_related('status', 'tipo').order_by('ordem', 'numero')

    totais = unidades.aggregate(
        ap=Sum('area_privativa'),
        apa=Sum('area_privativa_acessoria'),
        ac=Sum('area_comum'),
        fi=Sum('fracao_ideal'),
        vgv=Sum('valor_tabela'),
    )
    ap  = totais['ap']  or 0
    apa = totais['apa'] or 0
    ac  = totais['ac']  or 0
    ctx_totais = {
        'area_privativa':           ap,
        'area_privativa_acessoria': apa,
        'area_comum':               ac,
        'area_real_total':          ap + apa + ac,
        'fracao_ideal':             totais['fi']  or 0,
        'vgv':                      totais['vgv'] or 0,
    }

    return render_to_pdf('empreendimentos/bloco_pdf.html', {
        'empreendimento': empreendimento,
        'bloco': bloco,
        'unidades': unidades,
        'totais': ctx_totais,
    }, filename=f'{bloco.nome}.pdf')


class BlocoDetailView(LoginRequiredMixin, DetailView):
    model = Bloco
    template_name = 'empreendimentos/bloco_detail.html'
    context_object_name = 'bloco'
    pk_url_kwarg = 'bloco_pk'

    def get_object(self):
        return get_object_or_404(Bloco.all_objects, pk=self.kwargs['bloco_pk'], empreendimento_id=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        from django.db.models import Sum
        ctx = super().get_context_data(**kwargs)
        ctx['empreendimento'] = self.object.empreendimento
        unidades = self.object.unidades.select_related('status', 'tipo').order_by('ordem', 'numero')
        ctx['unidades'] = unidades

        totais = unidades.aggregate(
            area_privativa=Sum('area_privativa'),
            area_privativa_acessoria=Sum('area_privativa_acessoria'),
            area_comum=Sum('area_comum'),
            vgv=Sum('valor_tabela'),
        )
        ap  = totais['area_privativa'] or 0
        apa = totais['area_privativa_acessoria'] or 0
        ac  = totais['area_comum'] or 0
        ctx['totais'] = {
            'area_privativa':           ap,
            'area_privativa_acessoria': apa,
            'area_comum':               ac,
            'area_real_total':          ap + apa + ac,
            'vgv':                      totais['vgv'] or 0,
        }
        ctx['history_entries'] = _build_history(self.object)
        return ctx


class BlocoCreateView(LoginRequiredMixin, CreateView):
    model = Bloco
    template_name = 'empreendimentos/bloco_form.html'
    fields = ['nome', 'ordem']

    def get_empreendimento(self):
        return get_object_or_404(Empreendimento.objects, pk=self.kwargs['pk'])

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empreendimento'] = self.get_empreendimento()
        return ctx

    def form_valid(self, form):
        form.instance.empreendimento = self.get_empreendimento()
        messages.success(self.request, 'Bloco criado com sucesso.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('empreendimentos:empreendimento_detail', kwargs={'pk': self.kwargs['pk']})


class BlocoUpdateView(LoginRequiredMixin, UpdateView):
    model = Bloco
    template_name = 'empreendimentos/bloco_form.html'
    fields = ['nome', 'ordem']
    pk_url_kwarg = 'bloco_pk'

    def get_object(self):
        return get_object_or_404(Bloco.objects, pk=self.kwargs['bloco_pk'], empreendimento_id=self.kwargs['pk'])

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empreendimento'] = self.object.empreendimento
        return ctx

    def get_success_url(self):
        messages.success(self.request, 'Bloco atualizado com sucesso.')
        return reverse_lazy('empreendimentos:empreendimento_detail', kwargs={'pk': self.kwargs['pk']})


class BlocoDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk, bloco_pk):
        obj = get_object_or_404(Bloco.objects, pk=bloco_pk, empreendimento_id=pk)
        return render(request, 'empreendimentos/bloco_confirm_delete.html', {
            'object': obj,
            'empreendimento': obj.empreendimento,
        })

    def post(self, request, pk, bloco_pk):
        obj = get_object_or_404(Bloco.objects, pk=bloco_pk, empreendimento_id=pk)
        obj.soft_delete(user=request.user)
        messages.success(request, f'Bloco "{obj.nome}" excluído.')
        return redirect('empreendimentos:empreendimento_detail', pk=pk)


# ─── Unidade ───────────────────────────────────────────────────────────────────

_UNIDADE_FIELDS = [
    'numero', 'nome_exibicao', 'ordem', 'adicionais', 'status', 'tipo', 'tipologia', 'localizacao',
    'area_privativa', 'area_privativa_acessoria', 'area_comum',
    'fracao_ideal', 'valor_tabela',
    'descricao_1', 'descricao_2', 'descricao_3',
    'gars_tab_vendas', 'hb_tab_vendas',
    'linha', 'descricao_linha', 'coluna',
]


class UnidadeDetailView(LoginRequiredMixin, DetailView):
    model = Unidade
    template_name = 'empreendimentos/unidade_detail.html'
    context_object_name = 'unidade'
    pk_url_kwarg = 'unidade_pk'

    def get_object(self):
        return get_object_or_404(
            Unidade.all_objects.select_related('bloco__empreendimento', 'status', 'tipo'),
            pk=self.kwargs['unidade_pk'],
            bloco_id=self.kwargs['bloco_pk'],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['bloco'] = self.object.bloco
        ctx['empreendimento'] = self.object.bloco.empreendimento
        ctx['history_entries'] = _build_history(self.object)
        ctx['complementares'] = (
            self.object.complementares
            .select_related('status', 'tipo', 'bloco')
            .prefetch_related('designacoes')
            .all()
        )
        ctx['designacoes'] = self.object.designacoes.all()
        ctx['unidades_vinculaveis'] = (
            Unidade.objects
            .filter(
                bloco__empreendimento=self.object.bloco.empreendimento,
                unidade_principal__isnull=True,
            )
            .filter(Q(tipo__isnull=True) | Q(tipo__categoria=TipoUnidade.COMPLEMENTAR))
            .exclude(pk=self.object.pk)
            .select_related('bloco', 'tipo')
            .order_by('bloco__nome', 'ordem', 'numero')
        )
        ctx['tipos_designacao'] = DesignacaoUnidade.TIPO_CHOICES
        return ctx


class UnidadeCreateView(LoginRequiredMixin, CreateView):
    model = Unidade
    template_name = 'empreendimentos/unidade_form.html'
    fields = _UNIDADE_FIELDS

    def get_bloco(self):
        return get_object_or_404(Bloco.objects, pk=self.kwargs['bloco_pk'], empreendimento_id=self.kwargs['pk'])

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        empresa = _get_empresa_atual(self.request)
        if empresa:
            form.fields['status'].queryset = StatusUnidade.objects.filter(empresa=empresa)
            form.fields['tipo'].queryset = TipoUnidade.objects.filter(empresa=empresa)
        return _style_form(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        bloco = self.get_bloco()
        ctx['bloco'] = bloco
        ctx['empreendimento'] = bloco.empreendimento
        return ctx

    def form_valid(self, form):
        form.instance.bloco = self.get_bloco()
        messages.success(self.request, 'Unidade criada com sucesso.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('empreendimentos:bloco_detail', kwargs={
            'pk': self.kwargs['pk'],
            'bloco_pk': self.kwargs['bloco_pk'],
        })


class UnidadeUpdateView(LoginRequiredMixin, UpdateView):
    model = Unidade
    template_name = 'empreendimentos/unidade_form.html'
    fields = _UNIDADE_FIELDS
    pk_url_kwarg = 'unidade_pk'

    def get_object(self):
        return get_object_or_404(
            Unidade.objects.select_related('bloco__empreendimento'),
            pk=self.kwargs['unidade_pk'],
            bloco_id=self.kwargs['bloco_pk'],
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        empresa = _get_empresa_atual(self.request)
        if empresa:
            form.fields['status'].queryset = StatusUnidade.objects.filter(empresa=empresa)
            form.fields['tipo'].queryset = TipoUnidade.objects.filter(empresa=empresa)
        return _style_form(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['bloco'] = self.object.bloco
        ctx['empreendimento'] = self.object.bloco.empreendimento
        return ctx

    def get_success_url(self):
        messages.success(self.request, 'Unidade atualizada com sucesso.')
        return reverse_lazy('empreendimentos:unidade_detail', kwargs={
            'pk': self.kwargs['pk'],
            'bloco_pk': self.kwargs['bloco_pk'],
            'unidade_pk': self.object.pk,
        })


class UnidadeDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk, bloco_pk, unidade_pk):
        obj = get_object_or_404(Unidade.objects, pk=unidade_pk, bloco_id=bloco_pk)
        return render(request, 'empreendimentos/unidade_confirm_delete.html', {
            'object': obj,
            'bloco': obj.bloco,
            'empreendimento': obj.bloco.empreendimento,
        })

    def post(self, request, pk, bloco_pk, unidade_pk):
        obj = get_object_or_404(Unidade.objects, pk=unidade_pk, bloco_id=bloco_pk)
        obj.soft_delete(user=request.user)
        messages.success(request, f'Unidade "{obj.numero}" excluída.')
        return redirect('empreendimentos:bloco_detail', pk=pk, bloco_pk=bloco_pk)


@login_required
def unidade_pdf(request, pk, bloco_pk, unidade_pk):
    unidade = get_object_or_404(
        Unidade.all_objects.select_related('bloco__empreendimento', 'status', 'tipo'),
        pk=unidade_pk, bloco_id=bloco_pk,
    )
    return render_to_pdf('empreendimentos/unidade_pdf.html', {'unidade': unidade}, filename=f'unidade-{unidade.numero}.pdf')


# ─── Vínculos e Designações ────────────────────────────────────────────────────

def _get_unidade(pk, bloco_pk, unidade_pk):
    return get_object_or_404(
        Unidade.objects.select_related('bloco__empreendimento'),
        pk=unidade_pk, bloco_id=bloco_pk, bloco__empreendimento_id=pk,
    )


@login_required
def vincular_complementar(request, pk, bloco_pk, unidade_pk):
    principal = _get_unidade(pk, bloco_pk, unidade_pk)
    if request.method == 'POST':
        comp_pk = request.POST.get('complementar_id')
        complementar = get_object_or_404(
            Unidade.objects,
            pk=comp_pk,
            bloco__empreendimento_id=pk,
            unidade_principal__isnull=True,
        )
        complementar.unidade_principal = principal
        complementar.save()
        messages.success(request, f'Unidade "{complementar.numero}" vinculada.')
    return redirect('empreendimentos:unidade_detail', pk=pk, bloco_pk=bloco_pk, unidade_pk=unidade_pk)


@login_required
def desvincular_complementar(request, pk, bloco_pk, unidade_pk, complementar_pk):
    if request.method == 'POST':
        complementar = get_object_or_404(
            Unidade.objects,
            pk=complementar_pk,
            unidade_principal_id=unidade_pk,
        )
        complementar.unidade_principal = None
        complementar.save()
        messages.success(request, f'Unidade "{complementar.numero}" desvinculada.')
    return redirect('empreendimentos:unidade_detail', pk=pk, bloco_pk=bloco_pk, unidade_pk=unidade_pk)


@login_required
def designacao_create(request, pk, bloco_pk, unidade_pk):
    unidade = _get_unidade(pk, bloco_pk, unidade_pk)
    if request.method == 'POST':
        tipo = request.POST.get('tipo', '').strip()
        nome = request.POST.get('nome', '').strip().upper()
        tipos_validos = dict(DesignacaoUnidade.TIPO_CHOICES)
        if tipo not in tipos_validos:
            messages.error(request, 'Tipo inválido.')
        elif not nome:
            messages.error(request, 'Informe o nome da designação.')
        elif DesignacaoUnidade.objects.filter(unidade=unidade, nome=nome).exists():
            messages.error(request, f'A designação "{nome}" já existe nesta unidade.')
        else:
            DesignacaoUnidade.objects.create(unidade=unidade, tipo=tipo, nome=nome)
            messages.success(request, f'Designação "{nome}" adicionada.')
    return redirect('empreendimentos:unidade_detail', pk=pk, bloco_pk=bloco_pk, unidade_pk=unidade_pk)


@login_required
def designacao_delete(request, pk, bloco_pk, unidade_pk, des_pk):
    if request.method == 'POST':
        des = get_object_or_404(DesignacaoUnidade, pk=des_pk, unidade_id=unidade_pk)
        nome = des.nome
        des.delete()
        messages.success(request, f'Designação "{nome}" removida.')
    return redirect('empreendimentos:unidade_detail', pk=pk, bloco_pk=bloco_pk, unidade_pk=unidade_pk)


# ─── Importação CSV ────────────────────────────────────────────────────────────

def _parse_decimal(val):
    val = val.strip().replace(',', '.')
    if not val:
        return None
    try:
        return Decimal(val)
    except InvalidOperation:
        return None


_MODELO_UNIDADES = [
    ['Empreendimento', 'Bloco', 'numero', 'ordem', 'adicionais', 'tipo', 'tipologia',
     'localizacao', 'area_privativa', 'area_privativa_acessoria', 'area_comum',
     'fracao_ideal', 'valor_tabela', 'status', 'descricao1', 'descricao2', 'descricao3',
     'linha', 'descricao_linha', 'coluna', 'gars_tab_vendas', 'hb_tab_vendas'],
    ['Residencial Alpha', 'Torre A', '101', '1', '', 'Apartamento', '2 quartos',
     'Frente', '65,00', '', '10,00', '0,00123456', '350000,00', 'Disponível', '', '', '',
     '1', '1º Andar', '1', '', ''],
]

_MODELO_VINCULOS = [
    ['tipo', 'principal', 'complementar', 'designacao_tipo'],
    ['1', '101', 'G10', ''],
    ['2', '101', 'HB01', 'Hobby box'],
    ['2', '101', 'M05', 'Garagem moto'],
]


@login_required
def modelo_importacao_csv(request, pk, tipo):
    get_object_or_404(Empreendimento.objects, pk=pk)

    modelos = {'unidades': (_MODELO_UNIDADES, 'modelo_unidades.csv'),
               'vinculos': (_MODELO_VINCULOS, 'modelo_vinculos.csv')}
    if tipo not in modelos:
        from django.http import Http404
        raise Http404

    linhas, nome_arquivo = modelos[tipo]
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
    writer = csv.writer(response, delimiter=';')
    writer.writerows(linhas)
    return response


@login_required
def importar_unidades(request, pk):
    empreendimento = get_object_or_404(Empreendimento.objects, pk=pk)
    empresa = empreendimento.empresa

    if request.method != 'POST':
        total_atual = sum(b.unidades.count() for b in empreendimento.blocos.all())
        return render(request, 'empreendimentos/importar_unidades.html', {
            'empreendimento': empreendimento,
            'total_atual': total_atual,
        })

    arquivo = request.FILES.get('arquivo')
    arquivo_vinculos = request.FILES.get('arquivo_vinculos')
    modo = request.POST.get('modo', 'atualizar')

    if not arquivo and not arquivo_vinculos:
        messages.error(request, 'Selecione ao menos um arquivo CSV.')
        return redirect('empreendimentos:importar_unidades', pk=pk)

    if arquivo:
        # Tenta UTF-8 com BOM; se falhar, tenta latin-1
        raw = arquivo.read()
        for enc in ('utf-8-sig', 'latin-1'):
            try:
                conteudo = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            messages.error(request, 'CSV de unidades: não foi possível decodificar o arquivo. Use UTF-8 ou Latin-1.')
            return redirect('empreendimentos:importar_unidades', pk=pk)

    if arquivo:
        reader = csv.DictReader(io.StringIO(conteudo), delimiter=';')
        faltando = _colunas_faltando(reader.fieldnames, _COLUNAS_UNIDADES)
        if faltando:
            messages.error(request, f'CSV de unidades: coluna(s) ausente(s): {", ".join(faltando)}')
            return redirect('empreendimentos:importar_unidades', pk=pk)
        # Colunas opcionais presentes no CSV
        cols_opcionais = set(reader.fieldnames or []) & _COLUNAS_UNIDADES_OPCIONAIS

        if modo == 'apagar_tudo':
            for bloco in empreendimento.blocos.all():
                for unidade in bloco.unidades.all():
                    unidade.soft_delete(user=request.user)

        criados = atualizados = 0
        erros = []

        for i, row in enumerate(reader, start=2):
            try:
                bloco_nome = row['Bloco'].strip()
                bloco, _ = Bloco.objects.get_or_create(
                    empreendimento=empreendimento,
                    nome=bloco_nome,
                    defaults={'ordem': 0},
                )

                status_nome = row['status'].strip()
                status = None
                if status_nome:
                    status, _ = StatusUnidade.objects.get_or_create(empresa=empresa, nome=status_nome)

                tipo_nome = row['tipo'].strip()
                tipo = None
                if tipo_nome:
                    tipo, _ = TipoUnidade.objects.get_or_create(empresa=empresa, nome=tipo_nome)

                dados = {
                    'ordem':                   int(row['ordem'].strip()) if row['ordem'].strip().isdigit() else 0,
                    'adicionais':              row['adicionais'].strip(),
                    'status':                  status,
                    'tipo':                    tipo,
                    'tipologia':               row['tipologia'].strip(),
                    'localizacao':             row['localizacao'].strip(),
                    'area_privativa':          _parse_decimal(row['area_privativa']),
                    'area_privativa_acessoria': _parse_decimal(row['area_privativa_acessoria']),
                    'area_comum':              _parse_decimal(row['area_comum']),
                    'fracao_ideal':            _parse_decimal(row['fracao_ideal']),
                    'valor_tabela':            _parse_decimal(row['valor_tabela']),
                    'descricao_1':             row['descricao1'].strip(),
                    'descricao_2':             row['descricao2'].strip(),
                    'descricao_3':             row['descricao3'].strip(),
                }
                # Campos opcionais: só inclui se a coluna estiver no CSV
                if 'linha' in cols_opcionais:
                    dados['linha'] = row.get('linha', '').strip()
                if 'descricao_linha' in cols_opcionais:
                    dados['descricao_linha'] = row.get('descricao_linha', '').strip()
                if 'coluna' in cols_opcionais:
                    val = row.get('coluna', '').strip()
                    dados['coluna'] = int(val) if val.isdigit() else None
                if 'gars_tab_vendas' in cols_opcionais:
                    dados['gars_tab_vendas'] = row.get('gars_tab_vendas', '').strip()
                if 'hb_tab_vendas' in cols_opcionais:
                    dados['hb_tab_vendas'] = row.get('hb_tab_vendas', '').strip()
                numero = row['numero'].strip()

                if modo == 'apagar_tudo':
                    Unidade.objects.create(bloco=bloco, numero=numero, **dados)
                    criados += 1
                else:
                    qs = Unidade.objects.filter(bloco=bloco, numero=numero)
                    if qs.exists():
                        qs.update(**dados)
                        atualizados += 1
                    else:
                        Unidade.objects.create(bloco=bloco, numero=numero, **dados)
                        criados += 1

            except Exception as e:
                erros.append(f'Linha {i} ({row.get("numero", "?")}): {e}')

        partes = []
        if criados:
            partes.append(f'{criados} criada{"s" if criados > 1 else ""}')
        if atualizados:
            partes.append(f'{atualizados} atualizada{"s" if atualizados > 1 else ""}')
        messages.success(request, f'Importação concluída: {", ".join(partes) or "nenhuma alteração"}.')

        for erro in erros[:10]:
            messages.warning(request, erro)
        if len(erros) > 10:
            messages.warning(request, f'... e mais {len(erros) - 10} erros omitidos.')

    if arquivo_vinculos:
        raw_v = arquivo_vinculos.read()
        for enc in ('utf-8-sig', 'latin-1'):
            try:
                conteudo_v = raw_v.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            messages.error(request, 'CSV de vínculos: não foi possível decodificar o arquivo.')
            return redirect('empreendimentos:empreendimento_detail', pk=pk)

        reader_v = csv.DictReader(io.StringIO(conteudo_v), delimiter=';')
        faltando_v = _colunas_faltando(reader_v.fieldnames, _COLUNAS_VINCULOS)
        if faltando_v:
            messages.error(request, f'CSV de vínculos: coluna(s) ausente(s): {", ".join(faltando_v)}')
            return redirect('empreendimentos:empreendimento_detail', pk=pk)

        processados_v = erros_v = 0
        for i, row in enumerate(reader_v, start=2):
            tipo_v = row.get('tipo', '').strip()
            num_princ = row.get('principal', '').strip()
            num_comp = row.get('complementar', '').strip()
            desig_label = row.get('designacao_tipo', '').strip()

            if tipo_v not in ('1', '2'):
                messages.warning(request, f'Vínculos linha {i}: tipo inválido "{tipo_v}". Use 1 ou 2.')
                erros_v += 1
                continue

            try:
                principal = Unidade.objects.get(
                    bloco__empreendimento=empreendimento,
                    numero=num_princ,
                )
                if tipo_v == '1':
                    complementar = Unidade.objects.get(
                        bloco__empreendimento=empreendimento,
                        numero=num_comp,
                    )
                    complementar.unidade_principal = principal
                    complementar.tipo_vinculo = Unidade.MATRICULA_PROPRIA
                    complementar.save(update_fields=['unidade_principal', 'tipo_vinculo'])
                else:
                    if desig_label:
                        desig_tipo = _TIPO_DESIGNACAO_LABEL.get(desig_label.lower())
                        if not desig_tipo:
                            messages.warning(request, f'Vínculos linha {i}: designacao_tipo inválido "{desig_label}".')
                            erros_v += 1
                            continue
                    else:
                        desig_tipo = _inferir_tipo_designacao(num_comp)
                        if not desig_tipo:
                            messages.warning(request, f'Vínculos linha {i}: não foi possível inferir tipo para "{num_comp}".')
                            erros_v += 1
                            continue
                    DesignacaoUnidade.objects.get_or_create(
                        unidade=principal,
                        nome=num_comp,
                        defaults={'tipo': desig_tipo},
                    )
                processados_v += 1
            except Unidade.DoesNotExist:
                messages.warning(request, f'Vínculos linha {i}: unidade "{num_princ}" ou "{num_comp}" não encontrada.')
                erros_v += 1

        messages.success(request, f'Vínculos: {processados_v} processado(s), {erros_v} erro(s).')

    return redirect('empreendimentos:empreendimento_detail', pk=pk)


# ─── Config: Status de Unidade ─────────────────────────────────────────────────

class StatusUnidadeListView(LoginRequiredMixin, EmpresaQuerysetMixin, ListView):
    model = StatusUnidade
    template_name = 'empreendimentos/config_status_list.html'
    context_object_name = 'items'


class StatusUnidadeCreateView(LoginRequiredMixin, CreateView):
    model = StatusUnidade
    template_name = 'empreendimentos/config_form.html'
    fields = ['nome', 'cor']
    success_url = reverse_lazy('empreendimentos:status_unidade_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = 'Novo status de unidade'
        ctx['cancel_url'] = reverse_lazy('empreendimentos:status_unidade_list')
        return ctx

    def form_valid(self, form):
        form.instance.empresa = _get_empresa_atual(self.request)
        messages.success(self.request, 'Status criado com sucesso.')
        return super().form_valid(form)


class StatusUnidadeUpdateView(LoginRequiredMixin, UpdateView):
    model = StatusUnidade
    template_name = 'empreendimentos/config_form.html'
    fields = ['nome', 'cor']
    success_url = reverse_lazy('empreendimentos:status_unidade_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = f'Editar status: {self.object.nome}'
        ctx['cancel_url'] = reverse_lazy('empreendimentos:status_unidade_list')
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Status atualizado com sucesso.')
        return super().form_valid(form)


class StatusUnidadeDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk):
        obj = get_object_or_404(StatusUnidade.objects, pk=pk)
        return render(request, 'empreendimentos/config_confirm_delete.html', {
            'object': obj,
            'titulo': 'Excluir status de unidade',
            'cancel_url': reverse_lazy('empreendimentos:status_unidade_list'),
        })

    def post(self, request, pk):
        obj = get_object_or_404(StatusUnidade.objects, pk=pk)
        obj.soft_delete(user=request.user)
        messages.success(request, f'Status "{obj.nome}" excluído.')
        return redirect('empreendimentos:status_unidade_list')


# ─── Config: Tipo de Unidade ───────────────────────────────────────────────────

class TipoUnidadeListView(LoginRequiredMixin, EmpresaQuerysetMixin, ListView):
    model = TipoUnidade
    template_name = 'empreendimentos/config_tipo_list.html'
    context_object_name = 'items'


class TipoUnidadeCreateView(LoginRequiredMixin, CreateView):
    model = TipoUnidade
    template_name = 'empreendimentos/config_form.html'
    fields = ['nome', 'categoria']
    success_url = reverse_lazy('empreendimentos:tipo_unidade_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = 'Novo tipo de unidade'
        ctx['cancel_url'] = reverse_lazy('empreendimentos:tipo_unidade_list')
        return ctx

    def form_valid(self, form):
        form.instance.empresa = _get_empresa_atual(self.request)
        messages.success(self.request, 'Tipo criado com sucesso.')
        return super().form_valid(form)


class TipoUnidadeUpdateView(LoginRequiredMixin, UpdateView):
    model = TipoUnidade
    template_name = 'empreendimentos/config_form.html'
    fields = ['nome', 'categoria']
    success_url = reverse_lazy('empreendimentos:tipo_unidade_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['titulo'] = f'Editar tipo: {self.object.nome}'
        ctx['cancel_url'] = reverse_lazy('empreendimentos:tipo_unidade_list')
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Tipo atualizado com sucesso.')
        return super().form_valid(form)


class TipoUnidadeDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk):
        obj = get_object_or_404(TipoUnidade.objects, pk=pk)
        return render(request, 'empreendimentos/config_confirm_delete.html', {
            'object': obj,
            'titulo': 'Excluir tipo de unidade',
            'cancel_url': reverse_lazy('empreendimentos:tipo_unidade_list'),
        })

    def post(self, request, pk):
        obj = get_object_or_404(TipoUnidade.objects, pk=pk)
        obj.soft_delete(user=request.user)
        messages.success(request, f'Tipo "{obj.nome}" excluído.')
        return redirect('empreendimentos:tipo_unidade_list')
