from django.urls import path
from . import views

app_name = 'intranet'

urlpatterns = [
    path('', views.welcome, name='welcome'),
]
