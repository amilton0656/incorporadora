import django.db.models.deletion
from django.db import migrations, models

TIPOS_PADRAO = [
    ('proponente',          'Proponente',            0),
    ('conjuge_proponente',  'Cônjuge do Proponente', 1),
    ('segundo_proponente',  'Segundo Proponente',    2),
    ('conjuge_segundo',     'Cônjuge do 2º Prop.',   3),
    ('interveniente',       'Interveniente',          4),
    ('corretor',            'Corretor',               5),
    ('imobiliaria',         'Imobiliária',            6),
    ('imobiliaria_parceira','Imobiliária Parceira',   7),
]


def criar_tipos_e_migrar(apps, schema_editor):
    Empresa = apps.get_model('core', 'Empresa')
    TipoParteNegociacao = apps.get_model('negociacoes', 'TipoParteNegociacao')
    ParteNegociacao = apps.get_model('negociacoes', 'ParteNegociacao')

    for empresa in Empresa.objects.all():
        slug_map = {}  # slug → TipoParteNegociacao
        for slug, nome, ordem in TIPOS_PADRAO:
            tipo_obj, _ = TipoParteNegociacao.objects.get_or_create(
                empresa=empresa, slug=slug,
                defaults={'nome': nome, 'ordem': ordem},
            )
            slug_map[slug] = tipo_obj

        # Migra partes existentes (tipo ainda é string neste ponto — via tipo_slug)
        for parte in ParteNegociacao.objects.filter(negociacao__empresa=empresa):
            slug = parte.tipo_slug or ''
            tipo_obj = slug_map.get(slug)
            if not tipo_obj:
                # Slug desconhecido → cria tipo personalizado
                tipo_obj, _ = TipoParteNegociacao.objects.get_or_create(
                    empresa=empresa, slug=slug,
                    defaults={'nome': slug.replace('_', ' ').title(), 'ordem': 99},
                )
            parte.tipo = tipo_obj
            parte.save(update_fields=['tipo'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_alter_empresa_table_alter_historicalempresa_table_and_more'),
        ('negociacoes', '0005_negociacao_tabela_fk'),
    ]

    operations = [
        # 1. Cria o novo model
        migrations.CreateModel(
            name='TipoParteNegociacao',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100, verbose_name='Nome')),
                ('slug', models.CharField(blank=True, max_length=30, verbose_name='Código interno')),
                ('ordem', models.PositiveIntegerField(default=0, verbose_name='Ordem')),
                ('empresa', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name='tipos_parte_negociacao', to='core.empresa')),
            ],
            options={
                'verbose_name': 'Tipo de Parte',
                'verbose_name_plural': 'Tipos de Parte',
                'db_table': 'inc_tipo_parte_negociacao',
                'ordering': ['ordem', 'nome'],
                'unique_together': {('empresa', 'nome')},
            },
        ),
        # 2. Renomeia a coluna tipo antiga para tipo_slug (preserva dados)
        migrations.RenameField(
            model_name='partenegociacao',
            old_name='tipo',
            new_name='tipo_slug',
        ),
        # 3. Adiciona nova coluna tipo (FK nullable temporariamente)
        migrations.AddField(
            model_name='partenegociacao',
            name='tipo',
            field=models.ForeignKey(
                null=True, blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='partes',
                to='negociacoes.tipopartenegociacao',
                verbose_name='Tipo',
            ),
        ),
        # 4. Migra os dados
        migrations.RunPython(criar_tipos_e_migrar, migrations.RunPython.noop),
        # 5. Remove o campo antigo
        migrations.RemoveField(model_name='partenegociacao', name='tipo_slug'),
        # 6. Torna tipo obrigatório
        migrations.AlterField(
            model_name='partenegociacao',
            name='tipo',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='partes',
                to='negociacoes.tipopartenegociacao',
                verbose_name='Tipo',
            ),
        ),
        # 7. Atualiza Meta
        migrations.AlterModelOptions(
            name='partenegociacao',
            options={
                'ordering': ['ordem', 'tipo__ordem', 'tipo__nome'],
                'verbose_name': 'Parte da Negociação',
                'verbose_name_plural': 'Partes da Negociação',
            },
        ),
    ]
