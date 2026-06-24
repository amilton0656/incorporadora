from django.contrib import admin
from .models import EtapaWorkflow, TransicaoWorkflow, Negociacao, ParteNegociacao, SerieNegociacao, HistoricoNegociacao

admin.site.register(EtapaWorkflow)
admin.site.register(TransicaoWorkflow)
admin.site.register(Negociacao)
admin.site.register(ParteNegociacao)
admin.site.register(SerieNegociacao)
admin.site.register(HistoricoNegociacao)
