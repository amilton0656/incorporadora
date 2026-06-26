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
from .models import (EtapaWorkflow, HistoricoReserva,
                     Proposta, ParteReserva,
                     Reserva, ReservaUnidade, SerieProposta,
                     TipoParteNegociacao, TransicaoWorkflow)
# Aliases de compatibilidade durante transição
HistoricoProposta = HistoricoReserva
ParteProposta = ParteReserva
PropostaUnidade = ReservaUnidade
SerieNegociacao = SerieProposta
Negociacao = Proposta

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
    """Gera lista de parcelas ordenadas por data a partir das sÃ©ries propostas."""
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
                'serie_label': serie.get_tipo_display() + (f' â€” {serie.descricao}' if serie.descricao else ''),
                'data': data,
                'valor': serie.valor_por_parcela,
            })
    parcelas.sort(key=lambda p: (p['data'] or _date.max))
    for i, p in enumerate(parcelas):
        p['ordem'] = i
    return parcelas


def _gerar_resumo(proposta, negociacao_atual, series):
    """Compara valores da tabela vs proposta por tipo de serie.
    proposta = Proposta; negociacao_atual = Negociacao (rodada) ativa; series = suas series.
    """
    from apps.vendas.models import TabelaSerie
    TIPO_LABEL = dict(TabelaSerie.TIPO_CHOICES)
    TIPO_ORDEM = ['ato', 'parcelas_mensais', 'reforcos', 'chaves', 'financiamento', 'dacao', 'outro']

    from apps.vendas.models import TabelaVendasItem as TVI_R, TabelaSerie as TS_R
    # alias para a funcao usar proposta no lugar de neg
    neg = proposta
    tabela_por_tipo = {}

    if neg.tabela_id:
        unidade_ids_r = list(PropostaUnidade.objects.filter(reserva=neg).values_list('unidade_id', flat=True))
        encontrados_r = set()
        for item in TVI_R.objects.filter(
            tabela_id=neg.tabela_id, unidade_id__in=unidade_ids_r
        ).prefetch_related('valores__serie'):
            encontrados_r.add(item.unidade_id)
            for v in item.valores.all():
                tipo = v.serie.tipo
                tabela_por_tipo[tipo] = tabela_por_tipo.get(tipo, Decimal('0')) + v.valor_total

        for serie in TS_R.objects.filter(tabela_id=neg.tabela_id):
            for nu in PropostaUnidade.objects.filter(reserva=neg).select_related('unidade'):
                if nu.unidade_id in encontrados_r:
                    continue
                tipo = serie.tipo
                val = serie.calcular_valor_parcela(nu.unidade.valor_tabela or Decimal('0'))
                tabela_por_tipo[tipo] = tabela_por_tipo.get(tipo, Decimal('0')) + val

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

    # Desconto vem da rodada atual (Negociacao), nao da Proposta
    desconto_pct   = (negociacao_atual.desconto_percentual if negociacao_atual else Decimal('0')) or Decimal('0')
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


# â”€â”€â”€ Kanban â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class EspelhoView(LoginRequiredMixin, View):
    template_name = 'reservas/espelho.html'

    def get(self, request, pk):
        from apps.empreendimentos.models import Empreendimento, Unidade
        empreendimento = get_object_or_404(Empreendimento.objects, pk=pk)

        # NegociaÃ§Ãµes ativas para marcar "Em Processo"
        em_processo_ids = set(
            PropostaUnidade.objects.filter(
                proposta__empreendimento=empreendimento,
                proposta__status=Reserva.STATUS_ATIVA,
            ).values_list('unidade_id', flat=True)
        )
        neg_por_unidade = {
            nu.unidade_id: nu.proposta
            for nu in PropostaUnidade.objects.filter(
                proposta__empreendimento=empreendimento,
                proposta__status=Reserva.STATUS_ATIVA,
            ).select_related('proposta')
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

        # Decide modo de exibiÃ§Ã£o:
        # Se alguma unidade tem linha/coluna â†’ modo grade
        # Caso contrÃ¡rio â†’ modo colunas por bloco (fallback)
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

            # Garagens e HBs: usa override se preenchido, senÃ£o busca nos vÃ­nculos
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
                # HBs de mesma matrÃ­cula: designaÃ§Ãµes dos complementares â†’ entre parÃªnteses
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
            # Agrupa unidades por bloco e constrÃ³i uma grade por bloco
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
    template_name = 'reservas/kanban.html'

    def get(self, request):
        empresa = _get_empresa(request)
        etapas = EtapaWorkflow.objects.filter(empresa=empresa).order_by('ordem') if empresa else []

        # Filtros
        emp_id = request.GET.get('empreendimento', '')
        q      = request.GET.get('q', '').strip()

        qs = Reserva.objects.filter(
            empresa=empresa, status=Reserva.STATUS_ATIVA
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
                'reservas': neg_por_etapa.get(e.pk, []),
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


# â”€â”€â”€ NegociaÃ§Ã£o CRUD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class NegociacaoForm(django_forms.ModelForm):
    tabela = django_forms.ModelChoiceField(
        queryset=None,
        required=False,
        label='Tabela de vendas',
        help_text='Selecione a tabela de onde virÃ£o os valores da proposta.',
    )

    # Campos extras nÃ£o presentes no model
    primeira_unidade = django_forms.ModelChoiceField(
        queryset=None, required=False, label='Primeira unidade',
        help_text='Unidade inicial da negociaÃ§Ã£o (apenas disponíveis).',
    )

    class Meta:
        model = Reserva
        fields = ['empreendimento', 'observacoes']
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
    template_name = 'reservas/proposta_form.html'

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
            'tipos_parte': TipoParteNegociacao.objects.filter(empresa=empresa) if empresa else [],
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
            return redirect('reservas:negociacao_create')

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

        from apps.vendas.models import TabelaVendas as TV
        tabela_id = request.POST.get('tabela_id') or None
        tabela_obj = TV.objects.filter(pk=tabela_id).first() if tabela_id else None

        neg = Negociacao(
            empresa=empresa,
            empreendimento=empreendimento,
            etapa=etapa,
            tabela=tabela_obj,
            data_abertura=data,
            desconto_percentual=_parse_decimal(request.POST.get('desconto_percentual', '0')),
            observacoes=request.POST.get('observacoes', '').strip(),
        )
        neg.save()
        HistoricoProposta.objects.create(
            reserva=neg, etapa_anterior=None, etapa_nova=etapa,
            usuario=request.user, observacao='Proposta criada.',
        )

        # Partes: imobiliaria e corretor (campos dedicados com slug fixo)
        ordem = 0
        for slug, campo in [('imobiliaria', 'imobiliaria_id'), ('corretor', 'corretor_id')]:
            pid = request.POST.get(campo)
            if pid:
                tipo_obj = _get_tipo_parte(empresa, slug)
                ParteProposta.objects.create(reserva=neg, pessoa_id=pid, tipo=tipo_obj, ordem=ordem)
                ordem += 1

        # Compradores: arrays paralelos partes_tipo (pk) + partes_pessoa
        for tipo_id, pid in zip(
            request.POST.getlist('partes_tipo'),
            request.POST.getlist('partes_pessoa'),
        ):
            if pid and tipo_id:
                tipo_obj = TipoParteNegociacao.objects.filter(pk=tipo_id).first()
                if tipo_obj:
                    ParteProposta.objects.create(reserva=neg, pessoa_id=pid, tipo=tipo_obj, ordem=ordem)
                    ordem += 1

        # Tabela global da proposta
        tabela_id = request.POST.get('tabela_id') or None

        # Unidades â€” tabela_item resolvido a partir da tabela global
        for uid in request.POST.getlist('unidades_id'):
            if uid:
                unidade = Unidade.objects.filter(pk=uid).first()
                if unidade:
                    item = TabelaVendasItem.objects.filter(
                        tabela_id=tabela_id, unidade=unidade
                    ).first() if tabela_id else None
                    PropostaUnidade.objects.get_or_create(
                        reserva=neg, unidade=unidade,
                        defaults={'tabela_item': item},
                    )

        # Cria rodada #1 e copia series da tabela como series propostas iniciais
        neg_atual = Proposta.objects.create(reserva=neg, numero=1, status='ativa')

        if neg.tabela_id:
            from apps.vendas.models import TabelaSerie, TabelaVendasItem as TVI2
            unidade_ids = list(PropostaUnidade.objects.filter(reserva=neg).values_list('unidade_id', flat=True))
            series_tabela = TabelaSerie.objects.filter(tabela_id=neg.tabela_id).order_by('tipo')

            for serie in series_tabela:
                valor_parcela = Decimal('0')
                encontrou_item = False

                for item in TVI2.objects.filter(
                    tabela_id=neg.tabela_id, unidade_id__in=unidade_ids
                ).prefetch_related('valores__serie'):
                    for v in item.valores.filter(serie=serie):
                        valor_parcela += v.valor
                        encontrou_item = True

                if not encontrou_item:
                    for nu in PropostaUnidade.objects.filter(reserva=neg).select_related('unidade'):
                        valor_parcela += serie.calcular_valor_parcela(nu.unidade.valor_tabela or Decimal('0'))

                SerieNegociacao.objects.create(
                    proposta=neg_atual,
                    tipo=serie.tipo,
                    quantidade=serie.quantidade,
                    valor_por_parcela=valor_parcela,
                    data_primeiro_vencimento=serie.data_primeiro_vencimento,
                    periodicidade=serie.periodicidade,
                    serie_ref=serie,
                )

        messages.success(request, f'Proposta #{neg.numero} criada com sucesso.')
        return redirect('reservas:negociacao_detail', pk=neg.pk)


class NegociacaoDetailView(LoginRequiredMixin, DetailView):
    model = Reserva
    template_name = 'reservas/proposta_detail.html'
    context_object_name = 'neg'

    def get_object(self):
        return get_object_or_404(Reserva.all_objects, pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        neg = self.object
        ctx['partes'] = neg.partes.select_related('pessoa__conjuge', 'tipo').prefetch_related(
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
        # Rodada ativa (Negociacao) dentro desta Proposta
        neg_atual = neg.proposta_ativa
        ctx['neg_atual']    = neg_atual
        ctx['todas_propostas'] = neg.propostas.order_by('numero')
        series = list(neg_atual.series.all()) if neg_atual else []
        ctx['series']    = series
        ctx['historico'] = neg.historico.select_related('etapa_anterior', 'etapa_nova', 'usuario').all()
        ctx['destinos']  = neg.etapa.destinos if neg.status == Reserva.STATUS_ATIVA else []

        # Calendario de parcelas
        ctx['calendario'] = _gerar_calendario(series)

        # Resumo Tabela Ã— Proposto Ã— DiferenÃ§a
        ctx['resumo'] = _gerar_resumo(neg, neg_atual, series)

        # Series da tabela: usa neg.tabela (global) e soma por unidade
        from apps.vendas.models import TabelaVendasItem as TVI
        tabela_por_tipo = {}
        tabela_label    = {}
        tabela_serie_info = {}

        if neg.tabela_id:
            from apps.vendas.models import TabelaSerie
            unidade_ids = list(neg.unidades.values_list('unidade_id', flat=True))

            # Tenta via TabelaVendasItem (unidade estÃ¡ na tabela)
            itens_encontrados = set()
            for item in TVI.objects.filter(
                tabela_id=neg.tabela_id, unidade_id__in=unidade_ids
            ).prefetch_related('valores__serie'):
                itens_encontrados.add(item.unidade_id)
                for v in item.valores.all():
                    tipo = v.serie.tipo
                    tabela_por_tipo[tipo] = tabela_por_tipo.get(tipo, Decimal('0')) + v.valor_total
                    if tipo not in tabela_label:
                        tabela_label[tipo] = v.serie.get_tipo_display()
                        tabela_serie_info[tipo] = {
                            'quantidade': v.serie.quantidade,
                            'periodicidade': v.serie.get_periodicidade_display() if v.serie.periodicidade else '',
                        }

            # Fallback: calcula via valor_tabela Ã— percentual para unidades nÃ£o encontradas
            series = list(TabelaSerie.objects.filter(tabela_id=neg.tabela_id))
            if series:
                for nu in neg.unidades.select_related('unidade').all():
                    if nu.unidade_id in itens_encontrados:
                        continue  # jÃ¡ calculado via item
                    valor_base = nu.unidade.valor_tabela or Decimal('0')
                    for serie in series:
                        tipo = serie.tipo
                        valor_serie = (valor_base * (serie.percentual or Decimal('0')) / Decimal('100'))
                        tabela_por_tipo[tipo] = tabela_por_tipo.get(tipo, Decimal('0')) + valor_serie
                        if tipo not in tabela_label:
                            tabela_label[tipo] = serie.get_tipo_display()
                            tabela_serie_info[tipo] = {
                                'quantidade': serie.quantidade,
                                'periodicidade': serie.get_periodicidade_display() if serie.periodicidade else '',
                            }

        TIPO_ORDEM = ['ato', 'parcelas_mensais', 'reforcos', 'chaves', 'financiamento', 'dacao', 'outro']
        ctx['tabela_series_resumo'] = [
            {'tipo': tipo, 'label': tabela_label[tipo],
             'total': tabela_por_tipo[tipo], 'info': tabela_serie_info[tipo]}
            for tipo in TIPO_ORDEM if tipo in tabela_por_tipo
        ]
        ctx['tabela_total'] = sum(tabela_por_tipo.values(), Decimal('0'))

        # Pessoas disponíveis para adicionar como parte
        empresa = _get_empresa(self.request)
        ctx['pessoas_disponiveis'] = Pessoa.objects.filter(empresa=empresa) if empresa else []
        from apps.vendas.models import TabelaVendas as TV
        ctx['tabelas_disponiveis'] = TV.objects.filter(
            empreendimento=neg.empreendimento, ativa=True
        ).order_by('nome') if empresa else []
        ctx['tipos_parte'] = TipoParteNegociacao.objects.filter(empresa=empresa) if empresa else []
        ctx['tipos_serie'] = SerieNegociacao.TIPO_CHOICES
        ctx['periodicidades'] = SerieNegociacao.PERIODICIDADE_CHOICES
        # Unidades disponíveis para adicionar (nÃ£o vinculadas ainda a esta negociaÃ§Ã£o)
        from apps.vendas.models import TabelaVendas as TV
        unidades_na_neg = set(neg.unidades.values_list('unidade_id', flat=True))
        ctx['unidades_disponiveis'] = Unidade.objects.filter(
            bloco__empreendimento=neg.empreendimento,
            unidade_principal__isnull=True,
            status__nome__icontains='disponív',
        ).exclude(pk__in=unidades_na_neg).select_related('bloco', 'status') if empresa else []

        return ctx


class NegociacaoDeleteView(LoginRequiredMixin, View):
    def get(self, request, pk):
        neg = get_object_or_404(Reserva.objects, pk=pk)
        return render(request, 'reservas/proposta_confirm_delete.html', {'neg': neg})

    def post(self, request, pk):
        neg = get_object_or_404(Reserva.objects, pk=pk)
        neg.soft_delete(user=request.user)
        messages.success(request, f'Proposta #{neg.numero} excluÃ­da.')
        return redirect('reservas:kanban')


class NegociacaoUpdateView(LoginRequiredMixin, UpdateView):
    model = Reserva
    form_class = NegociacaoForm
    template_name = 'reservas/proposta_form.html'

    def get_form(self, form_class=None):
        empresa = _get_empresa(self.request)
        form = NegociacaoForm(**self.get_form_kwargs(), empresa=empresa)
        return _style_form(form)

    def form_valid(self, form):
        messages.success(self.request, 'NegociaÃ§Ã£o atualizada.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('reservas:negociacao_detail', kwargs={'pk': self.object.pk})


# â”€â”€â”€ AvanÃ§o de etapa â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def avancar_etapa(request, pk):
    neg = get_object_or_404(Reserva.objects, pk=pk)
    if request.method != 'POST':
        return redirect('reservas:negociacao_detail', pk=pk)

    destino_id  = request.POST.get('etapa_destino')
    observacao  = request.POST.get('observacao', '')
    destino     = get_object_or_404(EtapaWorkflow, pk=destino_id)

    # Verifica se a transiÃ§Ã£o Ã© permitida
    if not TransicaoWorkflow.objects.filter(origem=neg.etapa, destino=destino).exists():
        messages.error(request, 'TransiÃ§Ã£o nÃ£o permitida.')
        return redirect('reservas:negociacao_detail', pk=pk)

    etapa_anterior = neg.etapa
    neg.etapa = destino
    neg.save(update_fields=['etapa', 'atualizado_em'])

    HistoricoProposta.objects.create(
        reserva=neg,
        etapa_anterior=etapa_anterior,
        etapa_nova=destino,
        usuario=request.user,
        observacao=observacao,
    )
    messages.success(request, f'NegociaÃ§Ã£o avanÃ§ada para "{destino.nome}".')
    return redirect('reservas:negociacao_detail', pk=pk)


# â”€â”€â”€ Partes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def api_conjuge_sugerido(request, pessoa_pk):
    """Retorna o cÃ´njuge cadastrado no perfil da pessoa."""
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
def negociacao_change_tabela(request, pk):
    if request.method != 'POST':
        return redirect('reservas:negociacao_detail', pk=pk)
    from apps.vendas.models import TabelaVendas as TV
    neg      = get_object_or_404(Reserva.objects, pk=pk)
    tabela_id = request.POST.get('tabela_id') or None
    tabela_obj = TV.objects.filter(pk=tabela_id, empreendimento=neg.empreendimento).first() if tabela_id else None
    neg.tabela = tabela_obj
    neg.save(update_fields=['tabela'])
    messages.success(request, f'Tabela de vendas {"atualizada para " + tabela_obj.nome if tabela_obj else "removida"}.')
    return redirect('reservas:negociacao_detail', pk=pk)


@login_required
def negociacao_nova_rodada(request, pk):
    """Cria nova Proposta para a Reserva, copiando series da proposta anterior."""
    if request.method != 'POST':
        return redirect('reservas:negociacao_detail', pk=pk)

    neg = get_object_or_404(Reserva.objects, pk=pk)
    ultima = neg.propostas.order_by('-numero').first()

    # Propostas podem coexistir ativas — nao inativa a anterior automaticamente
    novo_numero = (ultima.numero + 1) if ultima else 1
    nova = Proposta.objects.create(
        reserva=neg,
        numero=novo_numero,
        status=Proposta.STATUS_ATIVA,
    )

    # Copia as series da proposta anterior
    if ultima:
        for s in ultima.series.all():
            SerieProposta.objects.create(
                proposta=nova,
                tipo=s.tipo,
                descricao=s.descricao,
                quantidade=s.quantidade,
                valor_por_parcela=s.valor_por_parcela,
                data_primeiro_vencimento=s.data_primeiro_vencimento,
                periodicidade=s.periodicidade,
                serie_ref=s.serie_ref,
            )

    messages.success(request, f'Proposta #{nova.numero} criada.')
    return redirect('reservas:negociacao_detail', pk=pk)


@login_required
def negociacao_aprovar_rodada(request, pk, rodada_pk):
    """Aprova a Proposta especificada."""
    if request.method != 'POST':
        return redirect('reservas:negociacao_detail', pk=pk)
    neg = get_object_or_404(Reserva.objects, pk=pk)
    proposta = get_object_or_404(Proposta, pk=rodada_pk, reserva=neg)
    proposta.status = Proposta.STATUS_APROVADA
    proposta.save(update_fields=['status'])
    messages.success(request, f'Proposta #{proposta.numero} aprovada.')
    return redirect('reservas:negociacao_detail', pk=pk)


@login_required
def negociacao_reset_series(request, pk):
    """Limpa as sÃ©ries propostas e copia os valores da tabela de vendas vinculada."""
    if request.method != 'POST':
        return redirect('reservas:negociacao_detail', pk=pk)

    neg = get_object_or_404(Reserva.objects, pk=pk)

    if not neg.tabela_id:
        messages.error(request, 'Nenhuma tabela de vendas vinculada a esta proposta.')
        return redirect('reservas:negociacao_detail', pk=pk)

    from apps.vendas.models import TabelaSerie, TabelaVendasItem as TVI3

    # Garante rodada ativa; cria se nao existir
    neg_atual = neg.proposta_ativa
    if not neg_atual:
        neg_atual = Proposta.objects.create(reserva=neg, numero=1, status='ativa')

    # Apaga as series propostas existentes da rodada
    neg_atual.series.all().delete()  # series da proposta

    unidade_ids = list(neg.unidades.values_list('unidade_id', flat=True))
    series_tabela = TabelaSerie.objects.filter(tabela_id=neg.tabela_id).order_by('tipo')
    criadas = 0

    for serie in series_tabela:
        valor_parcela = Decimal('0')
        encontrou = False

        for item in TVI3.objects.filter(
            tabela_id=neg.tabela_id, unidade_id__in=unidade_ids
        ).prefetch_related('valores__serie'):
            for v in item.valores.filter(serie=serie):
                valor_parcela += v.valor
                encontrou = True

        if not encontrou:
            for nu in neg.unidades.select_related('unidade').all():
                valor_parcela += serie.calcular_valor_parcela(nu.unidade.valor_tabela or Decimal('0'))

        SerieNegociacao.objects.create(
            negociacao=neg_atual,
            tipo=serie.tipo,
            quantidade=serie.quantidade,
            valor_por_parcela=valor_parcela,
            data_primeiro_vencimento=serie.data_primeiro_vencimento,
            periodicidade=serie.periodicidade,
            serie_ref=serie,
        )
        criadas += 1

    messages.success(request, f'{criadas} serie(s) copiada(s) da tabela de vendas.')
    return redirect('reservas:negociacao_detail', pk=pk)


@login_required
def negociacao_unidade_add(request, pk):
    neg = get_object_or_404(Reserva.objects, pk=pk)
    if request.method == 'POST':
        unidade_id = request.POST.get('unidade_id')
        unidade = get_object_or_404(Unidade.objects, pk=unidade_id)
        # Usa a tabela global da negociaÃ§Ã£o para encontrar o item
        item = None
        if neg.tabela_id:
            item = TabelaVendasItem.objects.filter(tabela_id=neg.tabela_id, unidade=unidade).first()
        PropostaUnidade.objects.get_or_create(
            reserva=neg, unidade=unidade,
            defaults={'tabela_item': item},
        )
        messages.success(request, f'Unidade {unidade.numero} adicionada.')
    return redirect('reservas:negociacao_detail', pk=pk)


@login_required
def negociacao_unidade_remove(request, pk, nu_pk):
    neg = get_object_or_404(Reserva.objects, pk=pk)
    if request.method == 'POST':
        PropostaUnidade.objects.filter(pk=nu_pk, reserva=neg).delete()
        messages.success(request, 'Unidade removida.')
    return redirect('reservas:negociacao_detail', pk=pk)


def _get_tipo_parte(empresa, slug):
    """Busca TipoParteNegociacao por slug; cria se nÃ£o existir."""
    obj, _ = TipoParteNegociacao.objects.get_or_create(
        empresa=empresa, slug=slug,
        defaults={'nome': slug.replace('_', ' ').title(), 'ordem': 99},
    )
    return obj


@login_required
def parte_add(request, pk):
    neg = get_object_or_404(Reserva.objects, pk=pk)
    if request.method == 'POST':
        pessoa_id = request.POST.get('pessoa_id')
        tipo_id   = request.POST.get('tipo')
        if pessoa_id and tipo_id:
            pessoa    = get_object_or_404(Pessoa.objects, pk=pessoa_id)
            tipo_obj  = get_object_or_404(TipoParteNegociacao, pk=tipo_id)
            ordem     = neg.partes.count()
            ParteProposta.objects.create(reserva=neg, pessoa=pessoa, tipo=tipo_obj, ordem=ordem)
            messages.success(request, f'{tipo_obj.nome} adicionado.')
    return redirect('reservas:negociacao_detail', pk=pk)


@login_required
def parte_remove(request, pk, parte_pk):
    neg   = get_object_or_404(Reserva.objects, pk=pk)
    parte = get_object_or_404(ParteProposta, pk=parte_pk, reserva=neg)
    if request.method == 'POST':
        parte.delete()
        messages.success(request, 'Parte removida.')
    return redirect('reservas:negociacao_detail', pk=pk)


# â”€â”€â”€ SÃ©ries da proposta â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _parse_decimal(raw):
    try:
        clean = str(raw).replace('R$', '').replace('.', '').replace(',', '.').strip()
        return Decimal(clean or '0')
    except Exception:
        return Decimal('0')


@login_required
def serie_add(request, pk):
    neg = get_object_or_404(Reserva.objects, pk=pk)
    if request.method == 'POST':
        neg_atual = neg.proposta_ativa
        if not neg_atual:
            neg_atual = Proposta.objects.create(reserva=neg, numero=1, status='ativa')
        SerieNegociacao.objects.create(
            negociacao=neg_atual,
            tipo=request.POST.get('tipo', 'outro'),
            descricao=request.POST.get('descricao', ''),
            quantidade=int(request.POST.get('quantidade') or 1),
            valor_por_parcela=_parse_decimal(request.POST.get('valor_por_parcela', '0')),
            data_primeiro_vencimento=request.POST.get('data_primeiro_vencimento') or None,
            periodicidade=request.POST.get('periodicidade', ''),
        )
        messages.success(request, 'Serie adicionada.')
    return redirect('reservas:negociacao_detail', pk=pk)


@login_required
def serie_update(request, pk, serie_pk):
    neg   = get_object_or_404(Reserva.objects, pk=pk)
    neg_atual = neg.proposta_ativa
    serie = get_object_or_404(SerieProposta, pk=serie_pk, proposta=neg_atual) if neg_atual else None
    if not serie:
        messages.error(request, 'Serie nao encontrada.')
        return redirect('reservas:negociacao_detail', pk=pk)

    if request.method == 'POST':
        serie.descricao           = request.POST.get('descricao', '').strip()
        serie.quantidade          = int(request.POST.get('quantidade') or 1)
        raw_valor = request.POST.get('valor_por_parcela', '0').strip()
        # Aceita formato decimal puro (1234.56) ou BRL (1.234,56)
        if ',' in raw_valor:
            raw_valor = raw_valor.replace('.', '').replace(',', '.')
        try:
            serie.valor_por_parcela = Decimal(raw_valor or '0')
        except Exception:
            serie.valor_por_parcela = Decimal('0')
        serie.data_primeiro_vencimento = request.POST.get('data_primeiro_vencimento') or None
        serie.periodicidade       = request.POST.get('periodicidade', '') if serie.quantidade > 1 else ''
        serie.save()
        messages.success(request, f'SÃ©rie "{serie.get_tipo_display()}" atualizada.')
        return redirect('reservas:negociacao_detail', pk=pk)

    return render(request, 'reservas/serie_form.html', {
        'neg': neg,
        'serie': serie,
        'periodicidades': SerieNegociacao.PERIODICIDADE_CHOICES,
    })


@login_required
def serie_remove(request, pk, serie_pk):
    neg   = get_object_or_404(Reserva.objects, pk=pk)
    neg_atual = neg.proposta_ativa
    serie = get_object_or_404(SerieProposta, pk=serie_pk, proposta=neg_atual) if neg_atual else None
    if request.method == 'POST' and serie:
        serie.delete()
        messages.success(request, 'Serie removida.')
    return redirect('reservas:negociacao_detail', pk=pk)


# â”€â”€â”€ Config: Tipos de Parte â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class TipoParteListView(LoginRequiredMixin, EmpresaQuerysetMixin, ListView):
    model = TipoParteNegociacao
    template_name = 'reservas/config_tipos_parte.html'
    context_object_name = 'tipos'


class TipoParteForm(django_forms.ModelForm):
    class Meta:
        model = TipoParteNegociacao
        fields = ['nome', 'ordem']


class TipoParteCreateView(LoginRequiredMixin, CreateView):
    model = TipoParteNegociacao
    form_class = TipoParteForm
    template_name = 'reservas/config_tipo_parte_form.html'
    success_url = reverse_lazy('reservas:tipo_parte_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        form.instance.empresa = _get_empresa(self.request)
        messages.success(self.request, 'Tipo criado.')
        return super().form_valid(form)


class TipoParteUpdateView(LoginRequiredMixin, UpdateView):
    model = TipoParteNegociacao
    form_class = TipoParteForm
    template_name = 'reservas/config_tipo_parte_form.html'
    success_url = reverse_lazy('reservas:tipo_parte_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        messages.success(self.request, 'Tipo atualizado.')
        return super().form_valid(form)


class TipoParteDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        obj = get_object_or_404(TipoParteNegociacao, pk=pk)
        if obj.partes.exists():
            messages.error(request, 'NÃ£o Ã© possÃ­vel excluir um tipo em uso.')
        else:
            obj.delete()
            messages.success(request, f'Tipo "{obj.nome}" excluÃ­do.')
        return redirect('reservas:tipo_parte_list')


# â”€â”€â”€ Config: Etapas do Workflow â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class EtapaWorkflowListView(LoginRequiredMixin, EmpresaQuerysetMixin, ListView):
    model = EtapaWorkflow
    template_name = 'reservas/config_etapas.html'
    context_object_name = 'etapas'


class EtapaWorkflowForm(django_forms.ModelForm):
    class Meta:
        model = EtapaWorkflow
        fields = ['nome', 'cor', 'ordem', 'is_inicial']
        widgets = {'cor': django_forms.TextInput(attrs={'type': 'color'})}


class EtapaWorkflowCreateView(LoginRequiredMixin, CreateView):
    model = EtapaWorkflow
    form_class = EtapaWorkflowForm
    template_name = 'reservas/config_etapa_form.html'
    success_url = reverse_lazy('reservas:etapa_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        form.instance.empresa = _get_empresa(self.request)
        messages.success(self.request, 'Etapa criada.')
        return super().form_valid(form)


class EtapaWorkflowUpdateView(LoginRequiredMixin, UpdateView):
    model = EtapaWorkflow
    form_class = EtapaWorkflowForm
    template_name = 'reservas/config_etapa_form.html'
    success_url = reverse_lazy('reservas:etapa_list')

    def get_form(self, form_class=None):
        return _style_form(super().get_form(form_class))

    def form_valid(self, form):
        messages.success(self.request, 'Etapa atualizada.')
        return super().form_valid(form)


class EtapaWorkflowDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        etapa = get_object_or_404(EtapaWorkflow, pk=pk)
        if etapa.reservas.exists():
            messages.error(request, 'NÃ£o Ã© possÃ­vel excluir uma etapa com negociaÃ§Ãµes.')
        else:
            etapa.delete()
            messages.success(request, 'Etapa excluÃ­da.')
        return redirect('reservas:etapa_list')


# â”€â”€â”€ Config: TransiÃ§Ãµes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@login_required
def reordenar_etapas(request):
    """Recebe lista de IDs em nova ordem e atualiza o campo `ordem`."""
    import json
    if request.method != 'POST':
        return redirect('reservas:etapa_list')
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
        return redirect('reservas:etapa_list')
    empresa = _get_empresa(request)
    origem  = get_object_or_404(EtapaWorkflow, pk=origem_pk, empresa=empresa)
    destino = get_object_or_404(EtapaWorkflow, pk=destino_pk, empresa=empresa)
    obj, created = TransicaoWorkflow.objects.get_or_create(origem=origem, destino=destino)
    if not created:
        obj.delete()
    return redirect('reservas:transicoes', pk=origem_pk)


@login_required
def transicoes_view(request, pk):
    empresa = _get_empresa(request)
    etapa   = get_object_or_404(EtapaWorkflow, pk=pk, empresa=empresa)
    todas   = EtapaWorkflow.objects.filter(empresa=empresa).exclude(pk=pk).order_by('ordem')
    ativas  = set(etapa.transicoes_saida.values_list('destino_id', flat=True))
    return render(request, 'reservas/config_transicoes.html', {
        'etapa': etapa,
        'todas': todas,
        'ativas': ativas,
    })
