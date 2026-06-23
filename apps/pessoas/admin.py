from django.contrib import admin
from .models import Pessoa, PessoaPapel, TipoPapel

admin.site.register(TipoPapel)
admin.site.register(Pessoa)
admin.site.register(PessoaPapel)
