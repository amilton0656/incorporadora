import django.db.models.deletion
from django.db import migrations, models


def migrar_unidades(apps, schema_editor):
    """Move unidade/tabela_item existentes para NegociacaoUnidade."""
    Negociacao = apps.get_model('negociacoes', 'Negociacao')
    NegociacaoUnidade = apps.get_model('negociacoes', 'NegociacaoUnidade')
    for neg in Negociacao.objects.filter(unidade__isnull=False):
        NegociacaoUnidade.objects.get_or_create(
            negociacao=neg,
            unidade_id=neg.unidade_id,
            defaults={'tabela_item_id': neg.tabela_item_id},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('empreendimentos', '0015_cores_status_unidade'),
        ('negociacoes', '0002_historicalnegociacao_desconto_percentual_and_more'),
        ('vendas', '0005_tabelaserie_percentual'),
    ]

    operations = [
        # 1. Cria NegociacaoUnidade ANTES de remover os campos
        migrations.CreateModel(
            name='NegociacaoUnidade',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('negociacao', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='unidades', to='negociacoes.negociacao')),
                ('tabela_item', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='vendas.tabelavendasitem', verbose_name='Item da tabela de vendas')),
                ('unidade', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='negociacao_unidades', to='empreendimentos.unidade')),
            ],
            options={
                'verbose_name': 'Unidade da Negociação',
                'verbose_name_plural': 'Unidades da Negociação',
                'db_table': 'inc_negociacao_unidade',
                'ordering': ['unidade__bloco__ordem', 'unidade__ordem', 'unidade__numero'],
                'unique_together': {('negociacao', 'unidade')},
            },
        ),
        # 2. Migra dados existentes
        migrations.RunPython(migrar_unidades, migrations.RunPython.noop),
        # 3. Remove campos antigos
        migrations.RemoveField(model_name='historicalnegociacao', name='tabela_item'),
        migrations.RemoveField(model_name='historicalnegociacao', name='unidade'),
        migrations.RemoveField(model_name='negociacao', name='tabela_item'),
        migrations.RemoveField(model_name='negociacao', name='unidade'),
    ]
