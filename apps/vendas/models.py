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
    history = HistoricalRecords()

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Tabela de Vendas'
        verbose_name_plural = 'Tabelas de Vendas'

    def __str__(self):
        return f'{self.nome} — {self.empreendimento.nome}'


class TabelaVendasItem(models.Model):
    tabela = models.ForeignKey(
        TabelaVendas, on_delete=models.CASCADE, related_name='itens'
    )
    unidade = models.ForeignKey(
        Unidade, on_delete=models.PROTECT, related_name='tabela_itens'
    )

    ato_qtd = models.PositiveIntegerField('Qtd. ato', default=1)
    ato_valor = models.DecimalField('Valor ato', max_digits=14, decimal_places=2, default=Decimal('0'))

    parcelas_mensais_qtd = models.PositiveIntegerField('Qtd. parcelas mensais', default=0)
    parcelas_mensais_valor = models.DecimalField('Valor parcela mensal', max_digits=14, decimal_places=2, default=Decimal('0'))

    reforcos_qtd = models.PositiveIntegerField('Qtd. reforços', default=0)
    reforcos_valor = models.DecimalField('Valor reforço', max_digits=14, decimal_places=2, default=Decimal('0'))

    chaves_valor = models.DecimalField('Chaves', max_digits=14, decimal_places=2, default=Decimal('0'))
    financiamento_valor = models.DecimalField('Financiamento', max_digits=14, decimal_places=2, default=Decimal('0'))

    class Meta:
        ordering = ['unidade__bloco__ordem', 'unidade__ordem', 'unidade__numero']
        unique_together = ('tabela', 'unidade')
        verbose_name = 'Item da Tabela'
        verbose_name_plural = 'Itens da Tabela'

    def __str__(self):
        return f'{self.tabela.nome} — {self.unidade.numero}'

    @property
    def ato_total(self):
        return (self.ato_qtd or 0) * (self.ato_valor or Decimal('0'))

    @property
    def parcelas_mensais_total(self):
        return (self.parcelas_mensais_qtd or 0) * (self.parcelas_mensais_valor or Decimal('0'))

    @property
    def reforcos_total(self):
        return (self.reforcos_qtd or 0) * (self.reforcos_valor or Decimal('0'))

    @property
    def valor_total(self):
        return (
            self.ato_total +
            self.parcelas_mensais_total +
            self.reforcos_total +
            (self.chaves_valor or Decimal('0')) +
            (self.financiamento_valor or Decimal('0'))
        )
