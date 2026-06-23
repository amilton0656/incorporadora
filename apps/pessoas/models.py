from django.db import models
from simple_history.models import HistoricalRecords

from apps.core.models import Empresa, SoftDeleteModel


class TipoPapel(SoftDeleteModel):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='tipos_papel')
    nome = models.CharField('Nome', max_length=50)
    criado_em = models.DateTimeField(auto_now_add=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ['nome']
        unique_together = ('empresa', 'nome')
        verbose_name = 'Tipo de Papel'
        verbose_name_plural = 'Tipos de Papel'

    def __str__(self):
        return self.nome


class Pessoa(SoftDeleteModel):
    PF = 'pf'
    PJ = 'pj'
    TIPO_CHOICES = [('pf', 'Pessoa Física'), ('pj', 'Pessoa Jurídica')]

    ESTADO_CIVIL_CHOICES = [
        ('', '---------'),
        ('solteiro', 'Solteiro(a)'),
        ('casado', 'Casado(a)'),
        ('divorciado', 'Divorciado(a)'),
        ('viuvo', 'Viúvo(a)'),
        ('uniao_estavel', 'União Estável'),
        ('outro', 'Outro'),
    ]

    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='pessoas')
    tipo = models.CharField('Tipo', max_length=2, choices=TIPO_CHOICES, default='pf')

    # PF
    nome = models.CharField('Nome completo', max_length=150, blank=True)
    cpf = models.CharField('CPF', max_length=14, blank=True)
    rg = models.CharField('RG', max_length=20, blank=True)
    data_nascimento = models.DateField('Data de nascimento', null=True, blank=True)
    estado_civil = models.CharField('Estado civil', max_length=15, choices=ESTADO_CIVIL_CHOICES, blank=True)
    profissao = models.CharField('Profissão', max_length=100, blank=True)
    nacionalidade = models.CharField('Nacionalidade', max_length=50, blank=True, default='Brasileiro(a)')

    # PJ
    razao_social = models.CharField('Razão social', max_length=200, blank=True)
    nome_fantasia = models.CharField('Nome fantasia', max_length=150, blank=True)
    cnpj = models.CharField('CNPJ', max_length=18, blank=True)
    inscricao_estadual = models.CharField('Inscrição estadual', max_length=30, blank=True)

    # Contato
    email = models.EmailField('E-mail', blank=True)
    telefone = models.CharField('Telefone', max_length=20, blank=True)
    celular = models.CharField('Celular', max_length=20, blank=True)

    # Endereço
    cep = models.CharField('CEP', max_length=9, blank=True)
    logradouro = models.CharField('Logradouro', max_length=200, blank=True)
    numero = models.CharField('Número', max_length=10, blank=True)
    complemento = models.CharField('Complemento', max_length=100, blank=True)
    bairro = models.CharField('Bairro', max_length=100, blank=True)
    cidade = models.CharField('Cidade', max_length=100, blank=True)
    estado = models.CharField('UF', max_length=2, blank=True)

    observacoes = models.TextField('Observações', blank=True)

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        ordering = ['nome', 'razao_social']
        verbose_name = 'Pessoa'
        verbose_name_plural = 'Pessoas'

    def __str__(self):
        return self.nome_exibicao

    @property
    def nome_exibicao(self):
        if self.tipo == self.PF:
            return self.nome or '—'
        return self.nome_fantasia or self.razao_social or '—'

    @property
    def documento(self):
        return self.cpf if self.tipo == self.PF else self.cnpj


class PessoaPapel(models.Model):
    pessoa = models.ForeignKey(Pessoa, on_delete=models.CASCADE, related_name='papeis')
    papel = models.ForeignKey(TipoPapel, on_delete=models.PROTECT, related_name='pessoa_papeis')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('pessoa', 'papel')
        ordering = ['papel__nome']

    def __str__(self):
        return f'{self.pessoa} — {self.papel}'
