from decimal import Decimal

from django import forms as django_forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from apps.core.mixins import EmpresaQuerysetMixin
from apps.core.models import Empresa
from apps.empreendimentos.models import Empreendimento, Unidade
from apps.pessoas.models import Pessoa, TipoPapel
from apps.vendas.models import TabelaVendasItem
from .models import (EtapaWorkflow, HistoricoNegociacao, Negociacao,
                     ParteNegociacao, SerieNegociacao, TransicaoWorkflow)

_INPUT = ('w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm '
          'focus:outline-none focus:ring-2 focus:ring-brand focus:border-transparent transition')
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


def _get_empresa(request):
    empresa_id = request.session.get('empresa_id')
    return Empresa.objects.filter(pk=empresa_id).first() if empresa_id else None


def _get_etapa_inicial(empresa):
    return EtapaWorkflow.objects.filter(empresa=empresa, is_inicial=True).first() \
        or EtapaWorkflow.objects.filter(empresa=empresa).order_by('ordem').first()


# ─── Kanban ────────────────────────────────────────────────────────────────────

class EspelhoView(LoginRequiredMixin, View):
    template_name = 'negociacoes/espelho.html'

    def get(self, request, pk):
        from apps.empreendimentos.models import Empreendimento, Unidade
        empreendimento = get_object_or_404(Empreendimento.objects, pk=pk)

        # Negociações ativas para marcar "Em Processo"
        em_processo_ids = set(
            Negociacao.objects.filter(
                empreendimento=empreendimento,
                status=Negociacao.STATUS_ATIVA,
            ).values_list('unidade_id', flat=True)
        )
        neg_por_unidade = {
            n.unidade_id: n
            for n in Negociacao.objects.filter(
                empreendimento=empreendimento,
                status=Negociacao.STATUS_ATIVA,
            ).select_related('unidade')
        }

        # Busca todas as unidades principais com linha/coluna definidas
        unidades = Unidade.objects.filter(
            bloco__empreendimento=empreendimento,
            unidade_principal__isnull=True,
            deletado_em__isnull=True,
        ).select_related('status', 'bloco').order_by('bloco__ordem', 'ordem', 'numero')

        # Decide modo de exibição:
        # Se alguma unidade tem linha/coluna → modo grade
        # Caso contrário → modo colunas por bloco (fallback)
        usa_grade = unidades.filter(linha__gt='', coluna__isnull=False).exists()

        contadores = {}
        total = 0

        def _enriquecer(u):
            nonlocal total
            total += 1
            em_proc = u.pk in em_processo_ids
            status_nome = u.status.nome if u.status else 'Sem status'
            if em_proc:
                label, cor = 'Em Processo', '#3b82f6'
            else:
                label = status_nome
                cor = u.status.cor if u.status else '#9ca3af'
            contadores[label] = contadores.get(label, 0) + 1
            return {
                'unidade': u,
                'cor': cor,
                'label': label,
                'disponivel': not em_proc and u.status and 'ponív' in u.status.nome,
                'negociacao': neg_por_unidade.get(u.pk),
            }

        if usa_grade:
            # Modo grade: monta matriz {linha: {coluna: cell}}
            linhas_set = set()
            colunas_set = set()
            celulas = {}  # (linha, coluna) → cell

            descricao_linha_map = {}  # linha_codigo → descricao_linha
            for u in unidades:
                if u.linha and u.coluna is not None:
                    linhas_set.add(u.linha)
                    colunas_set.add(u.coluna)
                    celulas[(u.linha, u.coluna)] = _enriquecer(u)
                    if u.descricao_linha:
                        descricao_linha_map[u.linha] = u.descricao_linha

            def _ordem_linha(l):
                if l.upper() == 'SS': return (-2, l)
                if l.upper() == 'T':  return (-1, l)
                try:    return (int(l), l)
                except: return (999, l)

            linhas_ord  = sorted(linhas_set, key=_ordem_linha)
            colunas_ord = sorted(colunas_set)

            # grade: rows = linha, cols = coluna
            grade = []
            for linha in linhas_ord:
                row = {'linha': linha, 'celulas': []}
                for col in colunas_ord:
                    row['celulas'].append(celulas.get((linha, col)))
                grade.append(row)

            return render(request, self.template_name, {
                'empreendimento': empreendimento,
                'modo': 'grade',
                'grade': grade,
                'colunas_ord': colunas_ord,
                'descricao_linha_map': descricao_linha_map,
                'contadores': contadores,
                'total': total,
            })

        else:
            # Modo fallback: agrupa por bloco
            from collections import defaultdict
            blocos_dict = defaultdict(list)
            blocos_ordem = {}
            for u in unidades:
                blocos_dict[u.bloco].append(_enriquecer(u))
                blocos_ordem[u.bloco] = u.bloco.ordem

            blocos_data = [
                {'bloco': b, 'unidades': cells}
                for b, cells in sorted(blocos_dict.items(), key=lambda x: blocos_ordem[x[0]])
            ]
            return render(request, self.template_name, {
                'empreendimento': empreendimento,
                'modo': 'colunas',
                'blocos_data': blocos_data,
                'contadores': contadores,
                'total': total,
            })


class NegociacaoKanbanView(LoginRequiredMixin, View):
    template_name = 'negociacoes/kanban.html'

    def get(self, request):
        empresa = _get_empresa(request)
        etapas = EtapaWorkflow.objects.filter(empresa=empresa).order_by('ordem') if empresa else []

        # Filtros
        emp_id = request.GET.get('empreendimento', '')
        q      = request.GET.get('q', '').strip()

        qs = Negociacao.objects.filter(
            empresa=empresa, status=Negociacao.STATUS_ATIVA
        ).select_related('unidade__bloco__empreendimento', 'etapa').prefetch_related('partes__pessoa')

        if emp_id:
            qs = qs.filter(empreendimento_id=emp_id)
        if q:
            qs = qs.filter(
                Q(numero__icontains=q) |
                Q(partes__pessoa__nome__icontains=q) |
                Q(partes__pessoa__razao_social__icontains=q) |
                Q(unidade__numero__icontains=q)
            ).distinct()

        # Agrupa por etapa
        neg_por_etapa = {e.pk: [] for e in etapas}
        total_por_etapa = {e.pk: Decimal('0') for e in etapas}
        for neg in qs:
            if neg.etapa_id in neg_por_etapa:
                neg_por_etapa[neg.etapa_id].append(neg)
                total_por_etapa[neg.etapa_id] += neg.valor_negociado

        colunas = [
            {
                'etapa': e,
                'negociacoes': neg_por_etapa.get(e.pk, []),
                'total': total_por_etapa.get(e.pk, Decimal('0')),
            }
            for e in etapas
        ]

        empreendimentos = Empreendimento.objects.filter(empresa=empresa) if empresa else []

        return render(request, self.template_name, {
            'colunas': colunas,
            'empreendimentos': empreendimentos,
            'emp_id': emp_id,
            'q': q,
        })


# ─── Negociação CRUD ───────────────────────────────────────────────────────────

class NegociacaoForm(django_forms.ModelForm):
    class Meta:
        model = Negociacao
        fields = ['empreendimento', 'unidade', 'tabela_item', 'observacoes']
        widgets = {'observacoes': django_forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa:
            self.fields['empreendimento'].queryset = Empreendimento.objects.filter(empresa=empresa)
            self.fields['unidade'].queryset = Unidade.objects.filter(
                bloco__empreendimento__empresa=empresa,
                unidade_principal__isnull=True,
            ).select_related('bloco__empreendimento')
            self.fields['tabela_item'].queryset = TabelaVendasItem.objects.filter(
                tabela__empreendimento__empresa=empresa
            ).select_related('tabela', 'unidade')
        self.fields['tabela_item'].required = False


class NegociacaoCreateView(LoginRequiredMixin, CreateView):
    model = Negociacao
    form_class = NegociacaoForm
    template_name = 'negociacoes/negociacao_form.html'

    def get_form(self, form_class=None):
        empresa = _get_empresa(self.request)
        form = NegociacaoForm(**self.get_form_kwargs(), empresa=empresa)
        return _style_form(form)

    def form_valid(self, form):
        empresa = _get_empresa(self.request)
        form.instance.empresa = empresa
        etapa = _get_etapa_inicial(empresa)
        if not etapa:
            messages.error(self.request, 'Configure ao menos uma etapa do workflow antes de criar uma negociação.')
            return self.form_invalid(form)
        form.instance.etapa = etapa
        response = super().form_valid(form)
        HistoricoNegociacao.objects.create(
            negociacao=self.object,
            etapa_anterior=None,
            etapa_nova=etapa,
            usuario=self.request.user,
            observacao='Negociação criada.',
        )
        messages.success(self.request, f'Negociação #{self.object.numero} criada.')
        return response

    def get_success_url(self):
        return reverse_lazy('negociacoes:negociacao_detail', kwargs={'pk': self.object.pk})


class NegociacaoDetailView(LoginRequiredMixin, DetailView):
    model = Negociacao
    template_name = 'negociacoes/negociacao_detail.html'
    context_object_name = 'neg'

    def get_object(self):
        return get_object_or_404(Negociacao.all_objects, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        neg = self.object
        ctx['partes']   = neg.partes.select_related('pessoa').all()
        ctx['series']   = neg.series.all()
        ctx['historico'] = neg.historico.select_related('etapa_anterior', 'etapa_nova', 'usuario').all()
        ctx['destinos'] = neg.etapa.destinos if neg.status == Negociacao.STATUS_ATIVA else []

        # Séries da tabela para comparação
        if neg.tabela_item:
            ctx['series_tabela'] = neg.tabela_item.tabela.series.all()
            ctx['valores_tabela'] = {
                v.serie_id: v for v in neg.tabela_item.valores.select_related('serie').all()
            }
        else:
            ctx['series_tabela'] = []
            ctx['valores_tabela'] = {}

        # Pessoas disponíveis para adicionar como parte
        empresa = _get_empresa(self.request)
        ctx['pessoas_disponiveis'] = Pessoa.objects.filter(empresa=empresa) if empresa else []
        ctx['tipos_parte'] = ParteNegociacao.TIPO_CHOICES
        ctx['tipos_serie'] = SerieNegociacao.TIPO_CHOICES
        ctx['periodicidades'] = SerieNegociacao.PERIODICIDADE_CHOICES
        return ctx


class NegociacaoUpdateView(LoginRequiredMixin, UpdateView):
    model = Negociacao
    form_class = NegociacaoForm
    template_name = 'negociacoes/negociacao_form.html'

    def get_form(self, form_class=None):
        empresa = _get_empresa(self.request)
        form = NegociacaoForm(**self.get_form_kwargs(), empresa=empresa)
        return _style_form(form)

    def form_valid(self, form):
        messages.success(self.request, 'Negociação atualizada.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('negociacoes:negociacao_detail', kwargs={'pk': self.object.pk})


# ─── Avanço de etapa ───────────────────────────────────────────────────────────

@login_required
def avancar_etapa(request, pk):
    neg = get_object_or_404(Negociacao.objects, pk=pk)
    if request.method != 'POST':
        return redirect('negociacoes:negociacao_detail', pk=pk)

    destino_id  = request.POST.get('etapa_destino')
    observacao  = request.POST.get('observacao', '')
    destino     = get_object_or_404(EtapaWorkflow, pk=destino_id)

    # Verifica se a transição é permitida
    if not TransicaoWorkflow.objects.filter(origem=neg.etapa, destino=destino).exists():
        messages.error(request, 'Transição não permitida.')
        return redirect('negociacoes:negociacao_detail', pk=pk)

    etapa_anterior = neg.etapa
    neg.etapa = destino
    neg.save(update_fields=['etapa', 'atualizado_em'])

    HistoricoNegociacao.objects.create(
        negociacao=neg,
        etapa_anterior=etapa_anterior,
        etapa_nova=destino,
        usuario=request.user,
        observacao=observacao,
    )
    messages.success(request, f'Negociação avançada para "{destino.nome}".')
    return redirect('negociacoes:negociacao_detail', pk=pk)


# ─── Partes ────────────────────────────────────────────────────────────────────

@login_required
def parte_add(request, pk):
    neg = get_object_or_404(Negociacao.objects, pk=pk)
    if request.method == 'POST':
        pessoa_id = request.POST.get('pessoa_id')
        tipo      = request.POST.get('tipo')
        if pessoa_id and tipo:
            pessoa = get_object_or_404(Pessoa.objects, pk=pessoa_id)
            ordem  = neg.partes.count()
            ParteNegociacao.objects.create(negociacao=neg, pessoa=pessoa, tipo=tipo, ordem=ordem)
            messages.success(request, f'{dict(ParteNegociacao.TIPO_CHOICES).get(tipo, tipo)} adicionado.')
    return redirect('negociacoes:negociacao_detail', pk=pk)


@login_required
def parte_remove(request, pk, parte_pk):
    neg   = get_object_or_404(Negociacao.objects, pk=pk)
    parte = get_object_or_404(ParteNegociacao, pk=parte_pk, negociacao=neg)
    if request.method == 'POST':
        parte.delete()
        messages.success(request, 'Parte removida.')
    return redirect('negociacoes:negociacao_detail', pk=pk)


# ─── Séries da proposta ────────────────────────────────────────────────────────

def _parse_decimal(raw):
    try:
        clean = str(raw).replace('R$', '').replace('.', '').replace(',', '.').strip()
        return Decimal(clean or '0')
    except Exception:
        return Decimal('0')


@login_required
def serie_add(request, pk):
    neg = get_object_or_404(Negociacao.objects, pk=pk)
    if request.method == 'POST':
        SerieNegociacao.objects.create(
            negociacao=neg,
            tipo=request.POST.get('tipo', 'outro'),
            descricao=request.POST.get('descricao', ''),
            quantidade=int(request.POST.get('quantidade') or 1),
            valor_por_parcela=_parse_decimal(request.POST.get('valor_por_parcela', '0')),
            data_primeiro_vencimento=request.POST.get('data_primeiro_vencimento') or None,
            periodicidade=request.POST.get('periodicidade', ''),
        )
        messages.success(request, 'Série adicionada.')
    return redirect('negociacoes:negociacao_detail', pk=pk)


@login_required
def serie_remove(request, pk, serie_pk):
    neg   = get_object_or_404(Negociacao.objects, pk=pk)
    serie = get_object_or_404(SerieNegociacao, pk=serie_pk, negociacao=neg)
    if request.method == 'POST':
        serie.delete()
        messages.success(request, 'Série removida.')
    return redirect('negociacoes:negociacao_detail', pk=pk)


# ─── Config: Etapas do Workflow ────────────────────────────────────────────────

class EtapaWorkflowListView(LoginRequiredMixin, EmpresaQuerysetMixin, ListView):
    model = EtapaWorkflow
    template_name = 'negociacoes/config_etapas.html'
    context_object_name = 'etapas'


class EtapaWorkflowForm(django_forms.ModelForm):
    class Meta:
        model = EtapaWorkflow
        fields = ['nome', 'cor', 'ordem', 'is_inicial']
        widgets = {'cor': django_forms.TextInput(attrs={'type': 'color'})}


class EtapaWorkflowCreateView(LoginRequiredMixin, CreateView):
    model = EtapaWorkflow
    form_class = EtapaWorkflowForm
    template_name = 'negociacoes/config_etapa_form.html'
    success_url = reverse_lazy('negociacoes:etapa_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        form.instance.empresa = _get_empresa(self.request)
        messages.success(self.request, 'Etapa criada.')
        return super().form_valid(form)


class EtapaWorkflowUpdateView(LoginRequiredMixin, UpdateView):
    model = EtapaWorkflow
    form_class = EtapaWorkflowForm
    template_name = 'negociacoes/config_etapa_form.html'
    success_url = reverse_lazy('negociacoes:etapa_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        messages.success(self.request, 'Etapa atualizada.')
        return super().form_valid(form)


class EtapaWorkflowDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        etapa = get_object_or_404(EtapaWorkflow, pk=pk)
        if etapa.negociacoes.exists():
            messages.error(request, 'Não é possível excluir uma etapa com negociações.')
        else:
            etapa.delete()
            messages.success(request, 'Etapa excluída.')
        return redirect('negociacoes:etapa_list')


# ─── Config: Transições ────────────────────────────────────────────────────────

@login_required
def reordenar_etapas(request):
    """Recebe lista de IDs em nova ordem e atualiza o campo `ordem`."""
    import json
    if request.method != 'POST':
        return redirect('negociacoes:etapa_list')
    try:
        ids = json.loads(request.body).get('ids', [])
        empresa = _get_empresa(request)
        for i, etapa_id in enumerate(ids):
            EtapaWorkflow.objects.filter(pk=etapa_id, empresa=empresa).update(ordem=i)
        from django.http import JsonResponse
        return JsonResponse({'ok': True})
    except Exception as e:
        from django.http import JsonResponse
        return JsonResponse({'ok': False, 'erro': str(e)}, status=400)


@login_required
def transicao_toggle(request, origem_pk, destino_pk):
    if request.method != 'POST':
        return redirect('negociacoes:etapa_list')
    empresa = _get_empresa(request)
    origem  = get_object_or_404(EtapaWorkflow, pk=origem_pk, empresa=empresa)
    destino = get_object_or_404(EtapaWorkflow, pk=destino_pk, empresa=empresa)
    obj, created = TransicaoWorkflow.objects.get_or_create(origem=origem, destino=destino)
    if not created:
        obj.delete()
    return redirect('negociacoes:transicoes', pk=origem_pk)


@login_required
def transicoes_view(request, pk):
    empresa = _get_empresa(request)
    etapa   = get_object_or_404(EtapaWorkflow, pk=pk, empresa=empresa)
    todas   = EtapaWorkflow.objects.filter(empresa=empresa).exclude(pk=pk).order_by('ordem')
    ativas  = set(etapa.transicoes_saida.values_list('destino_id', flat=True))
    return render(request, 'negociacoes/config_transicoes.html', {
        'etapa': etapa,
        'todas': todas,
        'ativas': ativas,
    })
