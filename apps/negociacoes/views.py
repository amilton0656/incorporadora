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


def _add_months(dt, months):
    """Soma N meses a uma data sem depender de dateutil."""
    import calendar as _cal
    if not dt or months == 0:
        return dt
    month = dt.month - 1 + months
    year  = dt.year + month // 12
    month = month % 12 + 1
    day   = min(dt.day, _cal.monthrange(year, month)[1])
    from datetime import date
    return date(year, month, day)


def _gerar_calendario(series):
    """Gera lista de parcelas ordenadas por data a partir das séries propostas."""
    from datetime import date as _date
    MESES = {
        'mensal': 1, 'bimestral': 2, 'trimestral': 3,
        'quadrimestral': 4, 'semestral': 6, 'anual': 12,
    }
    parcelas = []
    for serie in series:
        meses = MESES.get(serie.periodicidade, 0) if serie.periodicidade else 0
        for i in range(serie.quantidade or 1):
            if serie.data_primeiro_vencimento:
                data = _add_months(serie.data_primeiro_vencimento, i * meses) if meses else serie.data_primeiro_vencimento
            else:
                data = None
            parcelas.append({
                'serie_label': serie.get_tipo_display() + (f' — {serie.descricao}' if serie.descricao else ''),
                'data': data,
                'valor': serie.valor_por_parcela,
            })
    parcelas.sort(key=lambda p: (p['data'] or _date.max))
    for i, p in enumerate(parcelas):
        p['ordem'] = i
    return parcelas


def _gerar_resumo(neg, series):
    """Compara valores da tabela vs proposta por tipo de série."""
    from apps.vendas.models import TabelaSerie

    TIPO_LABEL = dict(TabelaSerie.TIPO_CHOICES)
    TIPO_ORDEM = ['ato', 'parcelas_mensais', 'reforcos', 'chaves', 'financiamento', 'dacao', 'outro']

    # Totais da tabela de referência — soma de todos os tabela_item das unidades
    from .models import NegociacaoUnidade
    tabela_por_tipo = {}
    for nu in NegociacaoUnidade.objects.filter(negociacao=neg, tabela_item__isnull=False).select_related('tabela_item'):
        for v in nu.tabela_item.valores.select_related('serie').all():
            tipo = v.serie.tipo
            tabela_por_tipo[tipo] = tabela_por_tipo.get(tipo, Decimal('0')) + v.valor_total

    # Totais da proposta agrupados por tipo
    proposta_por_tipo = {}
    for s in series:
        proposta_por_tipo[s.tipo] = proposta_por_tipo.get(s.tipo, Decimal('0')) + s.valor_total

    todos_tipos = set(list(tabela_por_tipo.keys()) + list(proposta_por_tipo.keys()))
    resumo = []
    for tipo in TIPO_ORDEM:
        if tipo in todos_tipos:
            vt = tabela_por_tipo.get(tipo, Decimal('0'))
            vp = proposta_por_tipo.get(tipo, Decimal('0'))
            resumo.append({
                'label': TIPO_LABEL.get(tipo, tipo),
                'tabela': vt,
                'proposto': vp,
                'diferenca': vp - vt,
            })

    total_tabela   = sum(tabela_por_tipo.values(),   Decimal('0'))
    total_proposto = sum(proposta_por_tipo.values(), Decimal('0'))

    # Aplicar desconto sobre o total proposto
    desconto_pct   = neg.desconto_percentual or Decimal('0')
    valor_desconto = (total_proposto * desconto_pct / Decimal('100')).quantize(Decimal('0.01'))
    total_com_desc = total_proposto - valor_desconto

    return {
        'linhas': resumo,
        'total_tabela': total_tabela,
        'total_proposto': total_proposto,
        'desconto_pct': desconto_pct,
        'valor_desconto': valor_desconto,
        'total_com_desconto': total_com_desc,
        'diferenca_total': total_proposto - total_tabela,
    }


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
        from .models import NegociacaoUnidade
        em_processo_ids = set(
            NegociacaoUnidade.objects.filter(
                negociacao__empreendimento=empreendimento,
                negociacao__status=Negociacao.STATUS_ATIVA,
            ).values_list('unidade_id', flat=True)
        )
        neg_por_unidade = {
            nu.unidade_id: nu.negociacao
            for nu in NegociacaoUnidade.objects.filter(
                negociacao__empreendimento=empreendimento,
                negociacao__status=Negociacao.STATUS_ATIVA,
            ).select_related('negociacao')
        }

        # Busca todas as unidades principais com linha/coluna definidas
        unidades = Unidade.objects.filter(
            bloco__empreendimento=empreendimento,
            unidade_principal__isnull=True,
            deletado_em__isnull=True,
        ).select_related('status', 'bloco').prefetch_related(
            'designacoes',
            'complementares__tipo',
            'complementares__designacoes',
        ).order_by('bloco__ordem', 'ordem', 'numero')

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

            # Garagens e HBs: usa override se preenchido, senão busca nos vínculos
            if u.gars_tab_vendas:
                gar_str = u.gars_tab_vendas
            else:
                gars = [d.nome for d in u.designacoes.all()
                        if d.tipo in ('garagem_carro', 'garagem_moto')]
                gars += [c.numero for c in u.complementares.all()
                         if c.tipo and 'aragem' in c.tipo.nome]
                gar_str = ' / '.join(gars)

            if u.hb_tab_vendas:
                hb_str = u.hb_tab_vendas
            else:
                hbs = [d.nome for d in u.designacoes.all() if d.tipo == 'hobby_box']
                hbs += [c.numero for c in u.complementares.all()
                        if c.tipo and 'obby' in c.tipo.nome]
                # HBs de mesma matrícula: designações dos complementares → entre parênteses
                for c in u.complementares.all():
                    hbs += [f'({d.nome})' for d in c.designacoes.all() if d.tipo == 'hobby_box']
                hb_str = ' / '.join(hbs)

            return {
                'unidade': u,
                'cor': cor,
                'label': label,
                'disponivel': not em_proc and u.status and 'ponív' in u.status.nome,
                'negociacao': neg_por_unidade.get(u.pk),
                'gar_str': gar_str,
                'hb_str': hb_str,
            }

        def _ordem_linha(l):
            if l.upper() == 'SS': return (-2, l)
            if l.upper() == 'T':  return (-1, l)
            try:    return (int(l), l)
            except: return (999, l)

        if usa_grade:
            # Agrupa unidades por bloco e constrói uma grade por bloco
            from collections import defaultdict, OrderedDict
            blocos_unidades = OrderedDict()
            for u in unidades:
                if u.bloco not in blocos_unidades:
                    blocos_unidades[u.bloco] = []
                blocos_unidades[u.bloco].append(u)

            blocos_grade = []
            descricao_linha_map = {}

            for bloco, units in blocos_unidades.items():
                linhas_set = set()
                colunas_set = set()
                celulas = {}

                for u in units:
                    if u.linha and u.coluna is not None:
                        linhas_set.add(u.linha)
                        colunas_set.add(u.coluna)
                        celulas[(u.linha, u.coluna)] = _enriquecer(u)
                        if u.descricao_linha:
                            descricao_linha_map[u.linha] = u.descricao_linha

                if not celulas:
                    continue

                linhas_ord  = sorted(linhas_set, key=_ordem_linha)
                colunas_ord = sorted(colunas_set)

                grade = []
                for linha in linhas_ord:
                    row = {'linha': linha, 'celulas': []}
                    for col in colunas_ord:
                        row['celulas'].append(celulas.get((linha, col)))
                    grade.append(row)

                # Contadores por bloco
                contadores_bloco = {}
                for cell in celulas.values():
                    contadores_bloco[cell['label']] = contadores_bloco.get(cell['label'], 0) + 1

                blocos_grade.append({
                    'bloco': bloco,
                    'grade': grade,
                    'colunas_ord': colunas_ord,
                    'total': len(celulas),
                    'contadores': contadores_bloco,
                })

            return render(request, self.template_name, {
                'empreendimento': empreendimento,
                'modo': 'grade',
                'blocos_grade': blocos_grade,
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
        ).select_related('empreendimento', 'etapa').prefetch_related(
            'partes__pessoa',
            'unidades__unidade__bloco',
        )

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
    tabela = django_forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Tabela de vendas',
        help_text='Selecione a tabela de onde virão os valores da proposta.',
    )

    # Campos extras não presentes no model
    primeira_unidade = django_forms.ModelChoiceField(
        queryset=None, required=False, label='Primeira unidade',
        help_text='Unidade inicial da negociação (apenas disponíveis).',
    )

    class Meta:
        model = Negociacao
        fields = ['empreendimento', 'desconto_percentual', 'observacoes']
        widgets = {'observacoes': django_forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.vendas.models import TabelaVendas
        if empresa:
            self.fields['empreendimento'].queryset = Empreendimento.objects.filter(empresa=empresa)
            self.fields['primeira_unidade'].queryset = Unidade.objects.filter(
                bloco__empreendimento__empresa=empresa,
                unidade_principal__isnull=True,
                status__nome__icontains='disponív',
            ).select_related('bloco__empreendimento')
            self.fields['tabela'].queryset = TabelaVendas.objects.filter(
                empreendimento__empresa=empresa,
                ativa=True,
            ).select_related('empreendimento').order_by('empreendimento__nome', 'nome')
        else:
            self.fields['primeira_unidade'].queryset = Unidade.objects.none()
            self.fields['tabela'].queryset = TabelaVendas.objects.none()


class NegociacaoCreateView(LoginRequiredMixin, View):
    template_name = 'negociacoes/negociacao_form.html'

    def _ctx(self, empresa):
        from apps.vendas.models import TabelaVendas as TV
        return {
            'empreendimentos': Empreendimento.objects.filter(empresa=empresa) if empresa else [],
            'pessoas': Pessoa.objects.filter(empresa=empresa).order_by('nome', 'razao_social') if empresa else [],
            'unidades': Unidade.objects.filter(
                bloco__empreendimento__empresa=empresa,
                unidade_principal__isnull=True,
                status__nome__icontains='disponív',
            ).select_related('bloco__empreendimento', 'status').order_by(
                'bloco__empreendimento__nome', 'bloco__ordem', 'ordem', 'numero'
            ) if empresa else [],
            'tabelas': TV.objects.filter(
                empreendimento__empresa=empresa, ativa=True
            ).select_related('empreendimento').order_by('empreendimento__nome', 'nome') if empresa else [],
            'tipos_parte': ParteNegociacao.TIPO_CHOICES,
            'tipos_serie': SerieNegociacao.TIPO_CHOICES,
            'periodicidades': SerieNegociacao.PERIODICIDADE_CHOICES,
        }

    def get(self, request):
        empresa = _get_empresa(request)
        ctx = self._ctx(empresa)
        ctx['preselect_unidade']       = request.GET.get('unidade', '')
        ctx['preselect_empreendimento'] = request.GET.get('empreendimento', '')
        return render(request, self.template_name, ctx)

    def post(self, request):
        from .models import NegociacaoUnidade
        empresa = _get_empresa(request)
        etapa   = _get_etapa_inicial(empresa)
        if not etapa:
            messages.error(request, 'Configure ao menos uma etapa do workflow antes de criar uma proposta.')
            return redirect('negociacoes:negociacao_create')

        emp_id = request.POST.get('empreendimento')
        if not emp_id:
            messages.error(request, 'Selecione um empreendimento.')
            return render(request, self.template_name, self._ctx(empresa))

        empreendimento = get_object_or_404(Empreendimento.objects, pk=emp_id, empresa=empresa)
        import datetime
        data_str = request.POST.get('data_abertura', '')
        try:
            data = datetime.date.fromisoformat(data_str) if data_str else datetime.date.today()
        except ValueError:
            data = datetime.date.today()

        neg = Negociacao(
            empresa=empresa,
            empreendimento=empreendimento,
            etapa=etapa,
            data_abertura=data,
            desconto_percentual=_parse_decimal(request.POST.get('desconto_percentual', '0')),
            observacoes=request.POST.get('observacoes', '').strip(),
        )
        neg.save()
        HistoricoNegociacao.objects.create(
            negociacao=neg, etapa_anterior=None, etapa_nova=etapa,
            usuario=request.user, observacao='Proposta criada.',
        )

        # Partes: imobiliária e corretor (campos dedicados)
        ordem = 0
        for tipo, campo in [('imobiliaria', 'imobiliaria_id'), ('corretor', 'corretor_id')]:
            pid = request.POST.get(campo)
            if pid:
                ParteNegociacao.objects.create(negociacao=neg, pessoa_id=pid, tipo=tipo, ordem=ordem)
                ordem += 1

        # Compradores: arrays paralelos partes_tipo + partes_pessoa
        for tipo, pid in zip(
            request.POST.getlist('partes_tipo'),
            request.POST.getlist('partes_pessoa'),
        ):
            if pid and tipo:
                ParteNegociacao.objects.create(negociacao=neg, pessoa_id=pid, tipo=tipo, ordem=ordem)
                ordem += 1

        # Tabela global da proposta
        tabela_id = request.POST.get('tabela_id') or None

        # Unidades — tabela_item resolvido a partir da tabela global
        for uid in request.POST.getlist('unidades_id'):
            if uid:
                unidade = Unidade.objects.filter(pk=uid).first()
                if unidade:
                    item = TabelaVendasItem.objects.filter(
                        tabela_id=tabela_id, unidade=unidade
                    ).first() if tabela_id else None
                    NegociacaoUnidade.objects.get_or_create(
                        negociacao=neg, unidade=unidade,
                        defaults={'tabela_item': item},
                    )

        # Séries (arrays paralelos)
        for tipo, desc, qtd, valor, data, period in zip(
            request.POST.getlist('series_tipo'),
            request.POST.getlist('series_descricao'),
            request.POST.getlist('series_quantidade'),
            request.POST.getlist('series_valor'),
            request.POST.getlist('series_data'),
            request.POST.getlist('series_periodicidade'),
        ):
            if tipo:
                SerieNegociacao.objects.create(
                    negociacao=neg,
                    tipo=tipo,
                    descricao=desc.strip(),
                    quantidade=int(qtd or 1),
                    valor_por_parcela=_parse_decimal(valor or '0'),
                    data_primeiro_vencimento=data or None,
                    periodicidade=period or '',
                )

        messages.success(request, f'Proposta #{neg.numero} criada com sucesso.')
        return redirect('negociacoes:negociacao_detail', pk=neg.pk)


class NegociacaoDetailView(LoginRequiredMixin, DetailView):
    model = Negociacao
    template_name = 'negociacoes/negociacao_detail.html'
    context_object_name = 'neg'

    def get_object(self):
        return get_object_or_404(Negociacao.all_objects, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        neg = self.object
        ctx['partes'] = neg.partes.select_related('pessoa__conjuge').prefetch_related(
            'pessoa__representantes_legais__pessoa_fisica'
        ).all()
        ctx['neg_unidades'] = neg.unidades.select_related(
            'unidade__status', 'unidade__bloco',
            'tabela_item__tabela',
        ).prefetch_related(
            'unidade__designacoes',
            'unidade__complementares__tipo',
            'unidade__complementares__designacoes',
        ).all()
        series = list(neg.series.all())
        ctx['series'] = series
        ctx['historico'] = neg.historico.select_related('etapa_anterior', 'etapa_nova', 'usuario').all()
        ctx['destinos']  = neg.etapa.destinos if neg.status == Negociacao.STATUS_ATIVA else []

        # Calendário de parcelas
        ctx['calendario'] = _gerar_calendario(series)

        # Resumo Tabela × Proposto × Diferença
        ctx['resumo'] = _gerar_resumo(neg, series)

        # Séries da tabela para comparação inline — usa o tabela_item da primeira unidade
        from .models import NegociacaoUnidade
        first_nu = NegociacaoUnidade.objects.filter(
            negociacao=neg, tabela_item__isnull=False
        ).select_related('tabela_item__tabela').first()
        if first_nu:
            ctx['series_tabela'] = first_nu.tabela_item.tabela.series.all()
            ctx['valores_tabela'] = {
                v.serie_id: v for v in first_nu.tabela_item.valores.select_related('serie').all()
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
        # Unidades disponíveis para adicionar (não vinculadas ainda a esta negociação)
        from apps.vendas.models import TabelaVendas as TV
        unidades_na_neg = set(neg.unidades.values_list('unidade_id', flat=True))
        ctx['unidades_disponiveis'] = Unidade.objects.filter(
            bloco__empreendimento=neg.empreendimento,
            unidade_principal__isnull=True,
            status__nome__icontains='disponív',
        ).exclude(pk__in=unidades_na_neg).select_related('bloco', 'status') if empresa else []
        ctx['tabelas_disponiveis'] = TV.objects.filter(
            empreendimento=neg.empreendimento, ativa=True
        ) if empresa else []
        return ctx


class NegociacaoDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk):
        neg = get_object_or_404(Negociacao.objects, pk=pk)
        return render(request, 'negociacoes/negociacao_confirm_delete.html', {'neg': neg})

    def post(self, request, pk):
        neg = get_object_or_404(Negociacao.objects, pk=pk)
        neg.soft_delete(user=request.user)
        messages.success(request, f'Proposta #{neg.numero} excluída.')
        return redirect('negociacoes:kanban')


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
def api_conjuge_sugerido(request, pessoa_pk):
    """Retorna o cônjuge cadastrado no perfil da pessoa."""
    from django.http import JsonResponse
    try:
        pessoa = Pessoa.objects.select_related('conjuge').get(pk=pessoa_pk)
        if pessoa.conjuge:
            c = pessoa.conjuge
            return JsonResponse({'conjuges': [{'pk': c.pk, 'nome': c.nome_exibicao}]})
    except Pessoa.DoesNotExist:
        pass
    return JsonResponse({'conjuges': []})


@login_required
def negociacao_unidade_add(request, pk):
    from .models import NegociacaoUnidade
    neg = get_object_or_404(Negociacao.objects, pk=pk)
    if request.method == 'POST':
        unidade_id = request.POST.get('unidade_id')
        tabela_id  = request.POST.get('tabela_id') or None
        unidade = get_object_or_404(Unidade.objects, pk=unidade_id)
        item = None
        if tabela_id:
            item = TabelaVendasItem.objects.filter(tabela_id=tabela_id, unidade=unidade).first()
        NegociacaoUnidade.objects.get_or_create(
            negociacao=neg, unidade=unidade,
            defaults={'tabela_item': item},
        )
        messages.success(request, f'Unidade {unidade.numero} adicionada.')
    return redirect('negociacoes:negociacao_detail', pk=pk)


@login_required
def negociacao_unidade_remove(request, pk, nu_pk):
    from .models import NegociacaoUnidade
    neg = get_object_or_404(Negociacao.objects, pk=pk)
    if request.method == 'POST':
        NegociacaoUnidade.objects.filter(pk=nu_pk, negociacao=neg).delete()
        messages.success(request, 'Unidade removida.')
    return redirect('negociacoes:negociacao_detail', pk=pk)


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
