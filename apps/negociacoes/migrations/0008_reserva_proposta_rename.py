"""
Rename: Proposta->Reserva, Negociacao->Proposta, SerieNegociacao->SerieProposta
Table renames:
  inc_proposta          -> inc_reserva
  inc_proposta_unidade  -> inc_reserva_unidade
  inc_parte_proposta    -> inc_parte_reserva
  inc_historico_proposta-> inc_historico_reserva
  inc_historical_proposta-> inc_historical_reserva
  inc_negociacao        -> inc_proposta
  inc_serie_negociacao  -> inc_serie_proposta
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('negociacoes', '0007_proposta_negociacao_refactor'),
    ]

    operations = [
        # ════ 1. Proposta → Reserva ═══════════════════════════════════════════
        migrations.RenameModel('Proposta', 'Reserva'),
        migrations.AlterModelTable('Reserva', 'inc_reserva'),

        migrations.RenameModel('HistoricalProposta', 'HistoricalReserva'),
        migrations.AlterModelTable('HistoricalReserva', 'inc_historical_reserva'),

        # ════ 2. Modelos filhos da Reserva ════════════════════════════════════
        migrations.RenameModel('PropostaUnidade', 'ReservaUnidade'),
        migrations.AlterModelTable('ReservaUnidade', 'inc_reserva_unidade'),
        migrations.RenameField('ReservaUnidade', 'proposta', 'reserva'),
        migrations.AlterModelOptions('ReservaUnidade', {
            'ordering': ['unidade__bloco__ordem', 'unidade__ordem', 'unidade__numero'],
            'verbose_name': 'Unidade da Reserva',
            'verbose_name_plural': 'Unidades da Reserva',
        }),

        migrations.RenameModel('ParteProposta', 'ParteReserva'),
        migrations.AlterModelTable('ParteReserva', 'inc_parte_reserva'),
        migrations.RenameField('ParteReserva', 'proposta', 'reserva'),
        migrations.AlterModelOptions('ParteReserva', {
            'ordering': ['ordem', 'tipo__ordem', 'tipo__nome'],
            'verbose_name': 'Parte da Reserva',
            'verbose_name_plural': 'Partes da Reserva',
        }),

        migrations.RenameModel('HistoricoProposta', 'HistoricoReserva'),
        migrations.AlterModelTable('HistoricoReserva', 'inc_historico_reserva'),
        migrations.RenameField('HistoricoReserva', 'proposta', 'reserva'),

        # ════ 3. Negociacao → Proposta ════════════════════════════════════════
        migrations.RenameModel('Negociacao', 'Proposta'),
        migrations.AlterModelTable('Proposta', 'inc_proposta'),
        migrations.RenameField('Proposta', 'proposta', 'reserva'),
        migrations.AlterModelOptions('Proposta', {
            'ordering': ['numero'],
            'verbose_name': 'Proposta',
            'verbose_name_plural': 'Propostas',
        }),

        # ════ 4. SerieNegociacao → SerieProposta ══════════════════════════════
        migrations.RenameModel('SerieNegociacao', 'SerieProposta'),
        migrations.AlterModelTable('SerieProposta', 'inc_serie_proposta'),
        migrations.RenameField('SerieProposta', 'negociacao', 'proposta'),
        migrations.AlterModelOptions('SerieProposta', {
            'ordering': ['tipo', 'pk'],
            'verbose_name': 'Serie da Proposta',
            'verbose_name_plural': 'Series da Proposta',
        }),

        # ════ 5. Atualiza related_name em Reserva ═════════════════════════════
        migrations.AlterModelOptions('Reserva', {
            'ordering': ['-numero'],
            'verbose_name': 'Reserva',
            'verbose_name_plural': 'Reservas',
        }),
    ]
