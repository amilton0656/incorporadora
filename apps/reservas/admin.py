from django.contrib import admin
from .models import (EtapaWorkflow, TransicaoWorkflow,
                     Reserva, ReservaUnidade, ParteReserva, HistoricoReserva,
                     Proposta, SerieProposta, TipoParteNegociacao)

admin.site.register(EtapaWorkflow)
admin.site.register(TransicaoWorkflow)
admin.site.register(Reserva)
admin.site.register(ReservaUnidade)
admin.site.register(ParteReserva)
admin.site.register(Proposta)
admin.site.register(SerieProposta)
admin.site.register(TipoParteNegociacao)
