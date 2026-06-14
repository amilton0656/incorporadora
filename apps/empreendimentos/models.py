from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import Empresa, SoftDeleteModel


class StatusUnidade(SoftDeleteModel):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='status_unidade', verbose_name='Empresa')
    nome = models.CharField('Nome', max_length=50)
    criado_em = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Status de unidade'
        verbose_name_plural = 'Status de unidades'
        ordering = ['nome']
        unique_together = [('empresa', 'nome')]

    def __str__(self):
        return self.nome


class TipoUnidade(SoftDeleteModel):
    PRINCIPAL = 'principal'
    COMPLEMENTAR = 'complementar'
    CATEGORIA_CHOICES = [
        (PRINCIPAL, 'Principal'),
        (COMPLEMENTAR, 'Complementar'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='tipos_unidade', verbose_name='Empresa')
    nome = models.CharField('Nome', max_length=50)
    categoria = models.CharField('Categoria', max_length=12, choices=CATEGORIA_CHOICES, default=PRINCIPAL)
    criado_em = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Tipo de unidade'
        verbose_name_plural = 'Tipos de unidade'
        ordering = ['categoria', 'nome']
        unique_together = [('empresa', 'nome')]

    def __str__(self):
        return self.nome


class Empreendimento(SoftDeleteModel):
    PLANEJAMENTO = 'planejamento'
    EM_CONSTRUCAO = 'em_construcao'
    ENTREGUE = 'entregue'
    CANCELADO = 'cancelado'

    STATUS_CHOICES = [
        (PLANEJAMENTO, 'Planejamento'),
        (EM_CONSTRUCAO, 'Em construção'),
        (ENTREGUE, 'Entregue'),
        (CANCELADO, 'Cancelado'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='empreendimentos', verbose_name='Empresa')
    nome = models.CharField('Nome', max_length=200)
    status = models.CharField('Status', max_length=20, choices=STATUS_CHOICES, default=PLANEJAMENTO)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Empreendimento'
        verbose_name_plural = 'Empreendimentos'
        ordering = ['nome']

    def __str__(self):
        return self.nome

    @property
    def status_badge_class(self):
        return {
            self.PLANEJAMENTO: 'bg-yellow-100 text-yellow-700',
            self.EM_CONSTRUCAO: 'bg-blue-100 text-blue-700',
            self.ENTREGUE: 'bg-green-100 text-green-700',
            self.CANCELADO: 'bg-red-100 text-red-600',
        }.get(self.status, 'bg-gray-100 text-gray-500')


class Bloco(SoftDeleteModel):
    empreendimento = models.ForeignKey(
        Empreendimento, on_delete=models.CASCADE,
        related_name='blocos', verbose_name='Empreendimento',
    )
    nome = models.CharField('Nome', max_length=100)
    ordem = models.IntegerField('Ordem', default=0)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Bloco'
        verbose_name_plural = 'Blocos'
        ordering = ['ordem', 'nome']

    def __str__(self):
        return f'{self.empreendimento.nome} — {self.nome}'


class Unidade(SoftDeleteModel):
    MESMA_MATRICULA = 'mesma_matricula'
    MATRICULA_PROPRIA = 'matricula_propria'
    TIPO_VINCULO_CHOICES = [
        (MESMA_MATRICULA, 'Mesma matrícula'),
        (MATRICULA_PROPRIA, 'Matrícula própria'),
    ]

    bloco = models.ForeignKey(Bloco, on_delete=models.CASCADE, related_name='unidades', verbose_name='Bloco')
    unidade_principal = models.ForeignKey(
        'self',
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='complementares',
        verbose_name='Unidade principal',
    )
    tipo_vinculo = models.CharField(
        'Tipo de vínculo', max_length=17,
        choices=TIPO_VINCULO_CHOICES,
        blank=True,
    )
    numero = models.CharField('Número', max_length=15)
    nome_exibicao = models.CharField('Nome de exibição', max_length=50, blank=True)
    ordem = models.IntegerField('Ordem', default=0)
    adicionais = models.CharField('Adicionais', max_length=100, blank=True)
    status = models.ForeignKey(
        StatusUnidade, on_delete=models.PROTECT,
        related_name='unidades', verbose_name='Status',
        null=True, blank=True,
    )
    tipo = models.ForeignKey(
        TipoUnidade, on_delete=models.PROTECT,
        related_name='unidades', verbose_name='Tipo',
        null=True, blank=True,
    )
    tipologia = models.CharField('Tipologia', max_length=20, blank=True)
    localizacao = models.CharField('Localização', max_length=30, blank=True)
    area_privativa = models.DecimalField('Área privativa (m²)', max_digits=10, decimal_places=4, null=True, blank=True)
    area_privativa_acessoria = models.DecimalField('Área privativa acessória (m²)', max_digits=10, decimal_places=4, null=True, blank=True)
    area_comum = models.DecimalField('Área comum (m²)', max_digits=10, decimal_places=4, null=True, blank=True)
    fracao_ideal = models.DecimalField('Fração ideal', max_digits=12, decimal_places=8, null=True, blank=True)
    valor_tabela = models.DecimalField('Valor tabela (R$)', max_digits=14, decimal_places=2, null=True, blank=True)
    descricao_1 = models.CharField('Descrição 1', max_length=70, blank=True)
    descricao_2 = models.CharField('Descrição 2', max_length=70, blank=True)
    descricao_3 = models.CharField('Descrição 3', max_length=70, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Unidade'
        verbose_name_plural = 'Unidades'
        ordering = ['ordem', 'numero']

    @property
    def area_total(self):
        return (self.area_privativa or 0) + (self.area_privativa_acessoria or 0) + (self.area_comum or 0)

    def __str__(self):
        return f'{self.bloco.empreendimento.nome} / {self.bloco.nome} — {self.numero}'

    @property
    def display_numero(self):
        if self.nome_exibicao:
            return self.nome_exibicao
        nomes = [self.numero] + list(self.designacoes.values_list('nome', flat=True))
        return ' / '.join(nomes)


class DesignacaoUnidade(models.Model):
    GARAGEM_CARRO = 'garagem_carro'
    GARAGEM_MOTO = 'garagem_moto'
    HOBBY_BOX = 'hobby_box'

    TIPO_CHOICES = [
        (GARAGEM_CARRO, 'Garagem carro'),
        (GARAGEM_MOTO, 'Garagem moto'),
        (HOBBY_BOX, 'Hobby box'),
    ]

    unidade = models.ForeignKey(
        Unidade, on_delete=models.CASCADE,
        related_name='designacoes', verbose_name='Unidade',
    )
    tipo = models.CharField('Tipo', max_length=15, choices=TIPO_CHOICES)
    nome = models.CharField('Nome', max_length=20)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Designação'
        verbose_name_plural = 'Designações'
        ordering = ['tipo', 'nome']
        unique_together = [('unidade', 'nome')]

    def __str__(self):
        return f'{self.get_tipo_display()} — {self.nome}'
