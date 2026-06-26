from django.contrib import admin
from .models import (EtapaWorkflow, TransicaoWorkflow, Proposta, PropostaUnidade,
                     ParteProposta, Negociacao, SerieNegociacao, HistoricoProposta,
                     TipoParteNegociacao)

admin.site.register(EtapaWorkflow)
admin.site.register(TransicaoWorkflow)
admin.site.register(Proposta)
admin.site.register(PropostaUnidade)
admin.site.register(ParteProposta)
admin.site.register(Negociacao)
admin.site.register(SerieNegociacao)
admin.site.register(HistoricoProposta)
admin.site.register(TipoParteNegociacao)
