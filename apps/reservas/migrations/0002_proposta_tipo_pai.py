from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('reservas', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='proposta',
            name='tipo',
            field=models.CharField(
                verbose_name='Tipo',
                max_length=20,
                choices=[('proposta', 'Proposta'), ('contraproposta', 'Contraproposta')],
                default='proposta',
            ),
        ),
        migrations.AddField(
            model_name='proposta',
            name='proposta_pai',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='contropropostas',
                to='reservas.proposta',
                verbose_name='Proposta pai',
            ),
        ),
    ]
