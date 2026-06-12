from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deletado_em__isnull=True)


class SoftDeleteModel(models.Model):
    """
    Model base com soft delete.
    Use objects para registros ativos, all_objects para todos (incluindo deletados).
    """
    deletado_em = models.DateTimeField(null=True, blank=True, editable=False)
    deletado_por = models.ForeignKey(
        User,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        editable=False,
    )

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    def soft_delete(self, user=None):
        self.deletado_em = timezone.now()
        self.deletado_por = user
        self.save(update_fields=['deletado_em', 'deletado_por'])

    def restaurar(self):
        self.deletado_em = None
        self.deletado_por = None
        self.save(update_fields=['deletado_em', 'deletado_por'])

    @property
    def deletado(self):
        return self.deletado_em is not None

    class Meta:
        abstract = True


class Empresa(SoftDeleteModel):
    nome = models.CharField('Nome fantasia', max_length=150)
    razao_social = models.CharField('Razão social', max_length=200)
    cnpj = models.CharField('CNPJ', max_length=18, unique=True)
    email = models.EmailField('E-mail', blank=True)
    telefone = models.CharField('Telefone', max_length=20, blank=True)
    site = models.URLField('Site', blank=True)

    cep = models.CharField('CEP', max_length=9, blank=True)
    logradouro = models.CharField('Logradouro', max_length=200, blank=True)
    numero = models.CharField('Número', max_length=10, blank=True)
    complemento = models.CharField('Complemento', max_length=100, blank=True)
    bairro = models.CharField('Bairro', max_length=100, blank=True)
    cidade = models.CharField('Cidade', max_length=100, blank=True)
    estado = models.CharField('Estado (UF)', max_length=2, blank=True)

    ativo = models.BooleanField('Ativa', default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'
        ordering = ['nome']

    def __str__(self):
        return self.nome


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    empresas = models.ManyToManyField(
        Empresa,
        related_name='usuarios',
        verbose_name='Empresas',
        blank=True,
    )
    cargo = models.CharField('Cargo', max_length=100, blank=True)

    class Meta:
        verbose_name = 'Perfil de usuário'
        verbose_name_plural = 'Perfis de usuário'

    def __str__(self):
        return f'{self.user.username}'
