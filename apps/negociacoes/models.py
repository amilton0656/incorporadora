from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from simple_history.models import HistoricalRecords

import datetime as _dt
from apps.core.models import Empresa, SoftDeleteModel
from apps.empreendimentos.models import Empreendimento, Unidade
from apps.pessoas.models import Pessoa
from apps.vendas.models import TabelaSerie, TabelaVendasItem


def _date_hoje():
    return _dt.date.today()


# ─── Workflow ──────────────────────────────────────────────────────────────────

class EtapaWorkflow(models.Model):
    empresa    = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='etapas_workflow')
    nome       = models.CharField('Nome', max_length=100)
    cor        = models.CharField('Cor', max_length=7, default='#3B82F6')
    ordem      = models.PositiveIntegerField('Ordem', default=0)
    is_inicial = models.BooleanField('Etapa inicial', default=False)

    class Meta:
        db_table = 'inc_etapa_workflow'
        ordering = ['ordem', 'nome']
        verbose_name = 'Etapa do Workflow'
        verbose_name_plural = 'Etapas do Workflow'

    def __str__(self):
        return self.nome

    @property
    def destinos(self):
        return EtapaWorkflow.objects.filter(transicoes_entrada__origem=self).order_by('ordem')


class TransicaoWorkflow(models.Model):
    origem  = models.ForeignKey(EtapaWorkflow, on_delete=models.CASCADE, related_name='transicoes_saida')
    destino = models.ForeignKey(EtapaWorkflow, on_delete=models.CASCADE, related_name='transicoes_entrada')

    class Meta:
        db_table = 'inc_transicao_workflow'
        unique_together = ('origem', 'destino')
        verbose_name = 'Transição do Workflow'
        verbose_name_plural = 'Transições do Workflow'

    def __str__(self):
        return f'{self.origem} → {self.destino}'


# ─── Proposta ──────────────────────────────────────────────────────────────────

class Proposta(SoftDeleteModel):
    """Container principal da venda: partes, unidades, tabela e workflow."""
    STATUS_ATIVA     = 'ativa'
    STATUS_CANCELADA = 'cancelada'
    STATUS_VENDIDA   = 'vendida'
    STATUS_DISTRATO  = 'distrato'
    STATUS_CHOICES   = [
        (STATUS_ATIVA,     'Ativa'),
        (STATUS_CANCELADA, 'Cancelada'),
        (STATUS_VENDIDA,   'Vendida'),
        (STATUS_DISTRATO,  'Distrato'),
    ]

    numero         = models.PositiveIntegerField('Número', unique=True, editable=False)
    empresa        = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='propostas')
    empreendimento = models.ForeignKey(Empreendimento, on_delete=models.PROTECT, related_name='propostas')
    tabela         = models.ForeignKey(
                        'vendas.TabelaVendas', on_delete=models.SET_NULL,
                        null=True, blank=True, related_name='propostas',
                        verbose_name='Tabela de vendas',
                     )
    etapa          = models.ForeignKey(EtapaWorkflow, on_delete=models.PROTECT, related_name='propostas')
    status         = models.CharField('Status', max_length=10, choices=STATUS_CHOICES, default=STATUS_ATIVA)
    data_abertura  = models.DateField('Data da proposta', default=_date_hoje)
    observacoes    = models.TextField('Observações', blank=True)
    criado_em      = models.DateTimeField(auto_now_add=True)
    atualizado_em  = models.DateTimeField(auto_now=True)
    history        = HistoricalRecords(table_name='inc_historical_proposta')

    class Meta:
        db_table = 'inc_proposta'
        ordering = ['-numero']
        verbose_name = 'Proposta'
        verbose_name_plural = 'Propostas'

    def __str__(self):
        return f'Proposta #{self.numero}'

    def save(self, *args, **kwargs):
        if not self.numero:
            last = Proposta.all_objects.order_by('-numero').first()
            self.numero = (last.numero + 1) if last else 1
        super().save(*args, **kwargs)

    @property
    def proponente(self):
        parte = self.partes.filter(tipo__slug='proponente').first()
        return parte.pessoa if parte else None

    @property
    def unidade_principal(self):
        nu = self.unidades.select_related('unidade').first()
        return nu.unidade if nu else None

    @property
    def negociacao_ativa(self):
        """Última negociação (rodada) ativa."""
        return self.negociacoes.filter(status=Negociacao.STATUS_ATIVA).last()

    @property
    def valor_negociado(self):
        """Valor da rodada ativa (ou zero)."""
        neg = self.negociacao_ativa
        return neg.valor_proposto if neg else Decimal('0')


class PropostaUnidade(models.Model):
    """Unidades vinculadas a uma proposta."""
    proposta    = models.ForeignKey(Proposta, on_delete=models.CASCADE, related_name='unidades')
    unidade     = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name='proposta_unidades')
    tabela_item = models.ForeignKey(TabelaVendasItem, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='+')

    class Meta:
        db_table = 'inc_proposta_unidade'
        unique_together = ('proposta', 'unidade')
        ordering = ['unidade__bloco__ordem', 'unidade__ordem', 'unidade__numero']
        verbose_name = 'Unidade da Proposta'
        verbose_name_plural = 'Unidades da Proposta'

    def __str__(self):
        return f'Proposta #{self.proposta.numero} — {self.unidade.numero}'


# ─── Tipos de parte (configurável) ────────────────────────────────────────────

class TipoParteNegociacao(models.Model):
    SLUG_PROPONENTE          = 'proponente'
    SLUG_CONJUGE_PROPONENTE  = 'conjuge_proponente'
    SLUG_SEGUNDO_PROPONENTE  = 'segundo_proponente'
    SLUG_CONJUGE_SEGUNDO     = 'conjuge_segundo'
    SLUG_INTERVENIENTE       = 'interveniente'
    SLUG_CORRETOR            = 'corretor'
    SLUG_IMOBILIARIA         = 'imobiliaria'
    SLUG_IMOBILIARIA_PARCEIRA= 'imobiliaria_parceira'

    TIPOS_PADRAO = [
        (SLUG_PROPONENTE,          'Proponente'),
        (SLUG_SEGUNDO_PROPONENTE,  'Segundo Proponente'),
        (SLUG_INTERVENIENTE,       'Interveniente'),
        (SLUG_CORRETOR,            'Corretor'),
        (SLUG_IMOBILIARIA,         'Imobiliária'),
        (SLUG_IMOBILIARIA_PARCEIRA,'Imobiliária Parceira'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='tipos_parte_negociacao')
    nome    = models.CharField('Nome', max_length=100)
    slug    = models.CharField('Código interno', max_length=30, blank=True)
    ordem   = models.PositiveIntegerField('Ordem', default=0)

    class Meta:
        db_table = 'inc_tipo_parte_negociacao'
        ordering = ['ordem', 'nome']
        unique_together = ('empresa', 'nome')
        verbose_name = 'Tipo de Parte'
        verbose_name_plural = 'Tipos de Parte'

    def __str__(self):
        return self.nome


class ParteProposta(models.Model):
    """Partes envolvidas na proposta (imobiliária, corretor, proponentes, etc.)."""
    proposta = models.ForeignKey(Proposta, on_delete=models.CASCADE, related_name='partes')
    pessoa   = models.ForeignKey(Pessoa, on_delete=models.PROTECT, related_name='participacoes')
    tipo     = models.ForeignKey(TipoParteNegociacao, on_delete=models.PROTECT, related_name='partes')
    ordem    = models.PositiveIntegerField('Ordem', default=0)

    class Meta:
        db_table = 'inc_parte_proposta'
        ordering = ['ordem', 'tipo__ordem', 'tipo__nome']
        verbose_name = 'Parte da Proposta'
        verbose_name_plural = 'Partes da Proposta'

    def __str__(self):
        return f'{self.tipo.nome}: {self.pessoa}'


# ─── Negociação (rodada de valores) ───────────────────────────────────────────

class Negociacao(models.Model):
    """Rodada de negociação: conjunto de valores propostos dentro de uma Proposta."""
    STATUS_ATIVA    = 'ativa'
    STATUS_APROVADA = 'aprovada'
    STATUS_RECUSADA = 'recusada'
    STATUS_CHOICES  = [
        (STATUS_ATIVA,    'Ativa'),
        (STATUS_APROVADA, 'Aprovada'),
        (STATUS_RECUSADA, 'Recusada'),
    ]

    proposta            = models.ForeignKey(Proposta, on_delete=models.CASCADE, related_name='negociacoes')
    numero              = models.PositiveIntegerField('Rodada', editable=False)
    status              = models.CharField('Status', max_length=10, choices=STATUS_CHOICES, default=STATUS_ATIVA)
    desconto_percentual = models.DecimalField('Desconto (%)', max_digits=5, decimal_places=2,
                                              default=Decimal('0'), blank=True)
    observacoes         = models.TextField('Observações', blank=True)
    criado_em           = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inc_negociacao'
        ordering = ['numero']
        verbose_name = 'Negociação'
        verbose_name_plural = 'Negociações'

    def __str__(self):
        return f'Proposta #{self.proposta.numero} — Rodada #{self.numero}'

    def save(self, *args, **kwargs):
        if not self.numero:
            last = Negociacao.objects.filter(proposta=self.proposta).order_by('-numero').first()
            self.numero = (last.numero + 1) if last else 1
        super().save(*args, **kwargs)

    @property
    def valor_proposto(self):
        return sum((s.valor_total for s in self.series.all()), Decimal('0'))


# ─── Séries da negociação ──────────────────────────────────────────────────────

class SerieNegociacao(models.Model):
    """Séries de pagamento propostas em uma rodada de negociação."""
    TIPO_CHOICES = [
        ('ato',              'Ato'),
        ('parcelas_mensais', 'Parcelas Mensais'),
        ('reforcos',         'Reforços'),
        ('chaves',           'Chaves'),
        ('financiamento',    'Financiamento'),
        ('dacao',            'Dação'),
        ('outro',            'Outro'),
    ]
    PERIODICIDADE_CHOICES = [
        ('mensal',        'Mensal'),
        ('bimestral',     'Bimestral'),
        ('trimestral',    'Trimestral'),
        ('quadrimestral', 'Quadrimestral'),
        ('semestral',     'Semestral'),
        ('anual',         'Anual'),
    ]

    negociacao               = models.ForeignKey(Negociacao, on_delete=models.CASCADE, related_name='series')
    serie_ref                = models.ForeignKey(TabelaSerie, on_delete=models.SET_NULL,
                                                 null=True, blank=True, related_name='+')
    tipo                     = models.CharField('Tipo', max_length=20, choices=TIPO_CHOICES)
    descricao                = models.CharField('Descrição', max_length=100, blank=True)
    quantidade               = models.PositiveIntegerField('Qtd. parcelas', default=1)
    valor_por_parcela        = models.DecimalField('Valor por parcela', max_digits=14, decimal_places=2,
                                                    default=Decimal('0'))
    data_primeiro_vencimento = models.DateField('Data 1º vencimento', null=True, blank=True)
    periodicidade            = models.CharField('Periodicidade', max_length=15,
                                                choices=PERIODICIDADE_CHOICES, blank=True, default='')

    class Meta:
        db_table = 'inc_serie_negociacao'
        ordering = ['tipo', 'pk']
        verbose_name = 'Série da Negociação'
        verbose_name_plural = 'Séries da Negociação'

    def __str__(self):
        return f'{self.get_tipo_display()} ({self.quantidade}×)'

    @property
    def valor_total(self):
        return (self.quantidade or 0) * (self.valor_por_parcela or Decimal('0'))


# ─── Histórico de etapas da proposta ──────────────────────────────────────────

class HistoricoProposta(models.Model):
    proposta       = models.ForeignKey(Proposta, on_delete=models.CASCADE, related_name='historico')
    etapa_anterior = models.ForeignKey(EtapaWorkflow, on_delete=models.PROTECT,
                                       related_name='+', null=True, blank=True)
    etapa_nova     = models.ForeignKey(EtapaWorkflow, on_delete=models.PROTECT, related_name='+')
    usuario        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    data           = models.DateTimeField(auto_now_add=True)
    observacao     = models.TextField('Observação', blank=True)

    class Meta:
        db_table = 'inc_historico_proposta'
        ordering = ['-data']
        verbose_name = 'Histórico de Etapa'
        verbose_name_plural = 'Histórico de Etapas'

    def __str__(self):
        return f'Proposta #{self.proposta.numero} → {self.etapa_nova}'


