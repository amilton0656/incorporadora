from .models import Empresa


def empresa_atual(request):
    if not request.user.is_authenticated:
        return {}

    empresa_id = request.session.get('empresa_id')
    empresa = None

    if empresa_id:
        empresa = Empresa.objects.filter(pk=empresa_id, ativo=True).first()

    # para o seletor no navbar: superuser vê todas, usuário comum vê as suas
    if request.user.is_superuser:
        todas = Empresa.objects.filter(ativo=True)
    else:
        profile = getattr(request.user, 'profile', None)
        todas = profile.empresas.filter(ativo=True) if profile else Empresa.objects.none()

    return {
        'empresa_atual': empresa,
        'user_empresas': todas,
    }
