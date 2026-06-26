"""
Refatoração Proposta/Negociação:
- Negociacao (antigo) → Proposta  (container da venda)
- Novo Negociacao     → rodada de valores dentro de uma Proposta
- SerieNegociacao migrada do vínculo com Proposta para Negociacao (rodada)
"""
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


def criar_rodadas(apps, schema_editor):
    """Para cada Proposta, cria Negociacao #1 e move SerieNegociacao."""
    Proposta = apps.get_model('negociacoes', 'Proposta')
    Negociacao = apps.get_model('negociacoes', 'Negociacao')
    SerieNegociacao = apps.get_model('negociacoes', 'SerieNegociacao')

    for proposta in Proposta.objects.all():
        desconto = getattr(proposta, 'desconto_percentual', Decimal('0')) or Decimal('0')
        neg = Negociacao.objects.create(
            proposta=proposta,
            numero=1,
            status='ativa',
            desconto_percentual=desconto,
        )
        SerieNegociacao.objects.filter(proposta_old=proposta).update(negociacao=neg)


AUTH_APP = settings.AUTH_USER_MODEL.split('.')[0] if '.' in settings.AUTH_USER_MODEL else 'auth'


class Migration(migrations.Migration):

    dependencies = [
        ('negociacoes', '0006_tipo_parte_configuravel'),
        ('core', '0005_alter_empresa_table_alter_historicalempresa_table_and_more'),
        ('empreendimentos', '0015_cores_status_unidade'),
        ('pessoas', '0004_representante_legal'),
        ('vendas', '0005_tabelaserie_percentual'),
        (AUTH_APP, '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        # ════ 1. RENOMEIA Negociacao → Proposta ════════════════════════════════
        migrations.RenameModel('Negociacao', 'Proposta'),
        migrations.AlterModelTable('Proposta', 'inc_proposta'),

        migrations.RenameModel('HistoricalNegociacao', 'HistoricalProposta'),
        migrations.AlterModelTable('HistoricalProposta', 'inc_historical_proposta'),

        # ════ 2. RENOMEIA modelos filhos ═══════════════════════════════════════
        migrations.RenameModel('NegociacaoUnidade', 'PropostaUnidade'),
        migrations.AlterModelTable('PropostaUnidade', 'inc_proposta_unidade'),
        migrations.AlterModelOptions('PropostaUnidade', {
            'ordering': ['unidade__bloco__ordem', 'unidade__ordem', 'unidade__numero'],
            'verbose_name': 'Unidade da Proposta',
            'verbose_name_plural': 'Unidades da Proposta',
        }),

        migrations.RenameModel('ParteNegociacao', 'ParteProposta'),
        migrations.AlterModelTable('ParteProposta', 'inc_parte_proposta'),
        migrations.AlterModelOptions('ParteProposta', {
            'ordering': ['ordem', 'tipo__ordem', 'tipo__nome'],
            'verbose_name': 'Parte da Proposta',
            'verbose_name_plural': 'Partes da Proposta',
        }),

        migrations.RenameModel('HistoricoNegociacao', 'HistoricoProposta'),
        migrations.AlterModelTable('HistoricoProposta', 'inc_historico_proposta'),

        # ════ 3. RENOMEIA FKs nos modelos filhos (negociacao → proposta) ═══════
        migrations.RenameField('PropostaUnidade', 'negociacao', 'proposta'),
        migrations.RenameField('ParteProposta', 'negociacao', 'proposta'),
        migrations.RenameField('HistoricoProposta', 'negociacao', 'proposta'),

        # ════ 4. PREPARA SerieNegociacao: renomeia FK para proposta_old ════════
        migrations.RenameField('SerieNegociacao', 'negociacao', 'proposta_old'),

        # ════ 5. CRIA novo model Negociacao (rodada de valores) ════════════════
        migrations.CreateModel(
            name='Negociacao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('numero', models.PositiveIntegerField(editable=False, verbose_name='Rodada')),
                ('status', models.CharField(
                    choices=[('ativa', 'Ativa'), ('aprovada', 'Aprovada'), ('recusada', 'Recusada')],
                    default='ativa', max_length=10, verbose_name='Status',
                )),
                ('desconto_percentual', models.DecimalField(
                    blank=True, decimal_places=2, default=Decimal('0'),
                    max_digits=5, verbose_name='Desconto (%)',
                )),
                ('observacoes', models.TextField(blank=True, verbose_name='Observações')),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('proposta', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='negociacoes',
                    to='negociacoes.proposta',
                )),
            ],
            options={
                'verbose_name': 'Negociação',
                'verbose_name_plural': 'Negociações',
                'db_table': 'inc_negociacao',
                'ordering': ['numero'],
            },
        ),

        # ════ 6. ADICIONA novo FK negociacao em SerieNegociacao (nullable) ════
        migrations.AddField(
            model_name='serienegociacao',
            name='negociacao',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='series',
                to='negociacoes.negociacao',
            ),
        ),

        # ════ 7. MIGRA DADOS: cria rodadas + move séries ════════════════════
        migrations.RunPython(criar_rodadas, migrations.RunPython.noop),

        # ════ 8. TORNA negociacao obrigatório em SerieNegociacao ════════════
        migrations.AlterField(
            model_name='serienegociacao',
            name='negociacao',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='series',
                to='negociacoes.negociacao',
            ),
        ),

        # ════ 9. REMOVE campo antigo proposta_old de SerieNegociacao ════════
        migrations.RemoveField(model_name='serienegociacao', name='proposta_old'),

        # ════ 10. REMOVE desconto_percentual de Proposta (movido para Negociacao) ═
        migrations.RemoveField(model_name='proposta', name='desconto_percentual'),

        # ════ 11. ATUALIZA Meta da Proposta ════════════════════════════════════
        migrations.AlterModelOptions('Proposta', {
            'ordering': ['-numero'],
            'verbose_name': 'Proposta',
            'verbose_name_plural': 'Propostas',
        }),
    ]
