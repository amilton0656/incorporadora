from django.contrib import admin
from .models import Bloco, Empreendimento, StatusUnidade, TipoUnidade, Unidade

admin.site.register(Empreendimento)
admin.site.register(Bloco)
admin.site.register(Unidade)
admin.site.register(StatusUnidade)
admin.site.register(TipoUnidade)
