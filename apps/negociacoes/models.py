from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import Empresa, SoftDeleteModel
from apps.empreendimentos.models import Empreendimento, Unidade
from apps.pessoas.models import Pessoa
from apps.vendas.models import TabelaSerie, TabelaVendasItem


# ─── Workflow ──────────────────────────────────────────────────────────────────

class EtapaWorkflow(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='etapas_workflow')
    nome = models.CharField('Nome', max_length=100)
    cor = models.CharField('Cor', max_length=7, default='#3B82F6',
                           help_text='Cor hexadecimal, ex: #3B82F6')
    ordem = models.PositiveIntegerField('Ordem', default=0)
    is_inicial = models.BooleanField('Etapa inicial', default=False,
                                     help_text='Nova negociação entra nesta etapa')

    class Meta:
        db_table = 'inc_etapa_workflow'
        ordering = ['ordem', 'nome']
        verbose_name = 'Etapa do Workflow'
        verbose_name_plural = 'Etapas do Workflow'

    def __str__(self):
        return self.nome

    @property
    def destinos(self):
        return EtapaWorkflow.objects.filter(
            transicoes_entrada__origem=self
        ).order_by('ordem')


class TransicaoWorkflow(models.Model):
    origem = models.ForeignKey(EtapaWorkflow, on_delete=models.CASCADE, related_name='transicoes_saida')
    destino = models.ForeignKey(EtapaWorkflow, on_delete=models.CASCADE, related_name='transicoes_entrada')

    class Meta:
        db_table = 'inc_transicao_workflow'
        unique_together = ('origem', 'destino')
        verbose_name = 'Transição do Workflow'
        verbose_name_plural = 'Transições do Workflow'

    def __str__(self):
        return f'{self.origem} → {self.destino}'


# ─── Negociação ────────────────────────────────────────────────────────────────

class Negociacao(SoftDeleteModel):
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
    empresa        = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='negociacoes')
    empreendimento = models.ForeignKey(Empreendimento, on_delete=models.PROTECT, related_name='negociacoes')
    unidade        = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name='negociacoes')
    tabela_item    = models.ForeignKey(TabelaVendasItem, on_delete=models.SET_NULL,
                                       null=True, blank=True, related_name='negociacoes',
                                       verbose_name='Item da tabela de vendas')
    etapa          = models.ForeignKey(EtapaWorkflow, on_delete=models.PROTECT, related_name='negociacoes')
    status         = models.CharField('Status', max_length=10, choices=STATUS_CHOICES, default=STATUS_ATIVA)
    data_abertura  = models.DateField('Data de abertura', auto_now_add=True)
    observacoes    = models.TextField('Observações', blank=True)
    criado_em      = models.DateTimeField(auto_now_add=True)
    atualizado_em  = models.DateTimeField(auto_now=True)
    history        = HistoricalRecords(table_name='inc_historical_negociacao')

    class Meta:
        db_table = 'inc_negociacao'
        ordering = ['-numero']
        verbose_name = 'Negociação'
        verbose_name_plural = 'Negociações'

    def __str__(self):
        return f'#{self.numero} — {self.unidade}'

    def save(self, *args, **kwargs):
        if not self.numero:
            last = Negociacao.all_objects.order_by('-numero').first()
            self.numero = (last.numero + 1) if last else 1
        super().save(*args, **kwargs)

    @property
    def proponente(self):
        parte = self.partes.filter(tipo='proponente').first()
        return parte.pessoa if parte else None

    @property
    def valor_negociado(self):
        return sum((s.valor_total for s in self.series.all()), Decimal('0'))


# ─── Partes ────────────────────────────────────────────────────────────────────

class ParteNegociacao(models.Model):
    TIPO_CHOICES = [
        ('proponente',          'Proponente'),
        ('conjuge_proponente',  'Cônjuge do Proponente'),
        ('segundo_proponente',  'Segundo Proponente'),
        ('conjuge_segundo',     'Cônjuge do 2º Proponente'),
        ('interveniente',       'Interveniente'),
        ('corretor',            'Corretor'),
        ('imobiliaria',         'Imobiliária'),
        ('imobiliaria_parceira','Imobiliária Parceira'),
    ]

    negociacao = models.ForeignKey(Negociacao, on_delete=models.CASCADE, related_name='partes')
    pessoa     = models.ForeignKey(Pessoa, on_delete=models.PROTECT, related_name='participacoes')
    tipo       = models.CharField('Tipo', max_length=25, choices=TIPO_CHOICES)
    ordem      = models.PositiveIntegerField('Ordem', default=0)

    class Meta:
        db_table = 'inc_parte_negociacao'
        ordering = ['ordem', 'tipo']
        verbose_name = 'Parte da Negociação'
        verbose_name_plural = 'Partes da Negociação'

    def __str__(self):
        return f'{self.get_tipo_display()}: {self.pessoa}'


# ─── Séries da proposta ────────────────────────────────────────────────────────

class SerieNegociacao(models.Model):
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
        ('mensal',         'Mensal'),
        ('bimestral',      'Bimestral'),
        ('trimestral',     'Trimestral'),
        ('quadrimestral',  'Quadrimestral'),
        ('semestral',      'Semestral'),
        ('anual',          'Anual'),
    ]

    negociacao           = models.ForeignKey(Negociacao, on_delete=models.CASCADE, related_name='series')
    serie_ref            = models.ForeignKey(TabelaSerie, on_delete=models.SET_NULL,
                                             null=True, blank=True, related_name='+',
                                             verbose_name='Série de referência (tabela)')
    tipo                 = models.CharField('Tipo', max_length=20, choices=TIPO_CHOICES)
    descricao            = models.CharField('Descrição', max_length=100, blank=True)
    quantidade           = models.PositiveIntegerField('Qtd. parcelas', default=1)
    valor_por_parcela    = models.DecimalField('Valor por parcela', max_digits=14, decimal_places=2, default=Decimal('0'))
    data_primeiro_vencimento = models.DateField('Data 1º vencimento', null=True, blank=True)
    periodicidade        = models.CharField('Periodicidade', max_length=15,
                                            choices=PERIODICIDADE_CHOICES, blank=True, default='')

    class Meta:
        db_table = 'inc_serie_negociacao'
        ordering = ['tipo', 'pk']
        verbose_name = 'Série da Proposta'
        verbose_name_plural = 'Séries da Proposta'

    def __str__(self):
        return f'{self.get_tipo_display()} ({self.quantidade}×)'

    @property
    def valor_total(self):
        return (self.quantidade or 0) * (self.valor_por_parcela or Decimal('0'))


# ─── Histórico de etapas ───────────────────────────────────────────────────────

class HistoricoNegociacao(models.Model):
    negociacao      = models.ForeignKey(Negociacao, on_delete=models.CASCADE, related_name='historico')
    etapa_anterior  = models.ForeignKey(EtapaWorkflow, on_delete=models.PROTECT,
                                        related_name='+', null=True, blank=True)
    etapa_nova      = models.ForeignKey(EtapaWorkflow, on_delete=models.PROTECT, related_name='+')
    usuario         = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    data            = models.DateTimeField(auto_now_add=True)
    observacao      = models.TextField('Observação', blank=True)

    class Meta:
        db_table = 'inc_historico_negociacao'
        ordering = ['-data']
        verbose_name = 'Histórico de Etapa'
        verbose_name_plural = 'Histórico de Etapas'

    def __str__(self):
        return f'#{self.negociacao.numero} → {self.etapa_nova}'
