from django.db import migrations


PALETA = [
    # Verifica na ordem — padrão mais específico primeiro
    ('permuta/venda',  '#4f46e5'),
    ('permuta_venda',  '#4f46e5'),
    ('disponív',       '#16a34a'),
    ('disponivel',     '#16a34a'),
    ('vendid',         '#ef4444'),
    ('reservad',       '#f97316'),
    ('bloquead',       '#7c3aed'),
    ('permuta',        '#0891b2'),
    ('qa',             '#ca8a04'),
    ('vencid',         '#6b7280'),
    ('processo',       '#3b82f6'),
]


def aplicar_cores(apps, schema_editor):
    StatusUnidade = apps.get_model('empreendimentos', 'StatusUnidade')
    for status in StatusUnidade.objects.all():
        nome = status.nome.lower()
        for padrao, cor in PALETA:
            if padrao in nome:
                status.cor = cor
                status.save(update_fields=['cor'])
                break


class Migration(migrations.Migration):
    dependencies = [
        ('empreendimentos', '0014_historicalunidade_descricao_linha_and_more'),
    ]

    operations = [
        migrations.RunPython(aplicar_cores, migrations.RunPython.noop),
    ]
