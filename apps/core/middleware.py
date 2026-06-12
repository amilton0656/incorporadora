from django.shortcuts import redirect

ROTAS_LIVRES = {
    '/login/',
    '/logout/',
    '/admin/',
}


class EmpresaSelectorMiddleware:
    """
    Gerencia a empresa ativa na sessão.
    - Superuser: acesso total, sem empresa obrigatória na sessão.
    - 1 empresa: auto-seleciona e segue.
    - Múltiplas empresas: exige seleção antes de acessar qualquer módulo.
    - Sem empresa vinculada: redireciona para página informativa.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._deve_verificar(request):
            resultado = self._verificar_empresa(request)
            if resultado:
                return resultado
        return self.get_response(request)

    def _deve_verificar(self, request):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return False
        for rota in ROTAS_LIVRES:
            if request.path.startswith(rota):
                return False
        return True

    def _verificar_empresa(self, request):
        profile = getattr(request.user, 'profile', None)

        if profile is None:
            if request.path != '/sem-empresa/':
                return redirect('/sem-empresa/')
            return None

        empresas = list(profile.empresas.filter(ativo=True))

        if not empresas:
            if request.path != '/sem-empresa/':
                return redirect('/sem-empresa/')
            return None

        if len(empresas) == 1:
            request.session['empresa_id'] = empresas[0].pk
            return None

        # múltiplas empresas — exige seleção (welcome trata isso)
        if not request.session.get('empresa_id'):
            if request.path != '/':
                return redirect('/')
        return None
