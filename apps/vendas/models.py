from decimal import Decimal

from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import SoftDeleteModel
from apps.empreendimentos.models import Empreendimento, Unidade


class TabelaVendas(SoftDeleteModel):
    empreendimento = models.ForeignKey(
        Empreendimento, on_delete=models.CASCADE, related_name='tabelas_vendas'
    )
    nome = models.CharField('Nome', max_length=150)
    vigencia_inicio = models.DateField('Vigência início', null=True, blank=True)
    vigencia_fim = models.DateField('Vigência fim', null=True, blank=True)
    ativa = models.BooleanField('Ativa', default=True)
    observacoes = models.TextField('Observações', blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    history = HistoricalRecords(table_name='inc_historical_tabela_vendas')

    class Meta:
        db_table = 'inc_tabela_vendas'
        ordering = ['-criado_em']
        verbose_name = 'Tabela de Vendas'
        verbose_name_plural = 'Tabelas de Vendas'

    def __str__(self):
        return f'{self.nome} — {self.empreendimento.nome}'


class TabelaSerie(models.Model):
    ATO = 'ato'
    PARCELAS_MENSAIS = 'parcelas_mensais'
    REFORCOS = 'reforcos'
    CHAVES = 'chaves'
    FINANCIAMENTO = 'financiamento'

    TIPO_CHOICES = [
        (ATO, 'Ato'),
        (PARCELAS_MENSAIS, 'Parcelas Mensais'),
        (REFORCOS, 'Reforços'),
        (CHAVES, 'Chaves'),
        (FINANCIAMENTO, 'Financiamento'),
    ]
    TIPO_ORDEM = {ATO: 0, PARCELAS_MENSAIS: 1, REFORCOS: 2, CHAVES: 3, FINANCIAMENTO: 4}

    PERIODICIDADE_CHOICES = [
        ('mensal', 'Mensal'),
        ('bimestral', 'Bimestral'),
        ('trimestral', 'Trimestral'),
        ('quadrimestral', 'Quadrimestral'),
        ('semestral', 'Semestral'),
        ('anual', 'Anual'),
    ]

    tabela = models.ForeignKey(TabelaVendas, on_delete=models.CASCADE, related_name='series')
    tipo = models.CharField('Tipo', max_length=20, choices=TIPO_CHOICES)
    percentual = models.DecimalField('Percentual (%)', max_digits=5, decimal_places=2, default=Decimal('0'))
    quantidade = models.PositiveIntegerField('Qtd. parcelas', default=1)
    data_primeiro_vencimento = models.DateField('Data 1º vencimento', null=True, blank=True)
    periodicidade = models.CharField('Periodicidade', max_length=15, choices=PERIODICIDADE_CHOICES, blank=True, default='')

    class Meta:
        db_table = 'inc_tabela_serie'
        unique_together = ('tabela', 'tipo')
        ordering = ['tipo']
        verbose_name = 'Série'
        verbose_name_plural = 'Séries'

    def __str__(self):
        return f'{self.get_tipo_display()} ({self.quantidade}×)'

    @property
    def label(self):
        return f'{self.get_tipo_display()} ({self.quantidade}×)'

    def calcular_valor_parcela(self, valor_total):
        """Retorna o valor por parcela com base no valor total da unidade."""
        if not self.quantidade:
            return Decimal('0')
        valor_serie = (valor_total or Decimal('0')) * (self.percentual or Decimal('0')) / Decimal('100')
        return (valor_serie / self.quantidade).quantize(Decimal('0.01'))


class TabelaVendasItem(models.Model):
    tabela = models.ForeignKey(
        TabelaVendas, on_delete=models.CASCADE, related_name='itens'
    )
    unidade = models.ForeignKey(
        Unidade, on_delete=models.PROTECT, related_name='tabela_itens'
    )

    class Meta:
        db_table = 'inc_tabela_vendas_item'
        ordering = ['unidade__bloco__ordem', 'unidade__ordem', 'unidade__numero']
        unique_together = ('tabela', 'unidade')
        verbose_name = 'Item da Tabela'
        verbose_name_plural = 'Itens da Tabela'

    def __str__(self):
        return f'{self.tabela.nome} — {self.unidade.numero}'

    @property
    def valor_total(self):
        return sum(
            (v.valor_total for v in self.valores.select_related('serie').all()),
            Decimal('0'),
        )


class TabelaVendasItemValor(models.Model):
    item = models.ForeignKey(TabelaVendasItem, on_delete=models.CASCADE, related_name='valores')
    serie = models.ForeignKey(TabelaSerie, on_delete=models.CASCADE, related_name='valores')
    valor = models.DecimalField('Valor por parcela', max_digits=14, decimal_places=2, default=Decimal('0'))

    class Meta:
        db_table = 'inc_tabela_vendas_item_valor'
        unique_together = ('item', 'serie')
        verbose_name = 'Valor do Item'
        verbose_name_plural = 'Valores dos Itens'

    def __str__(self):
        return f'{self.item.unidade.numero} / {self.serie.get_tipo_display()}'

    @property
    def valor_total(self):
        return (self.serie.quantidade or 0) * (self.valor or Decimal('0'))
