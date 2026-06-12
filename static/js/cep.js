function initCepLookup(cepInputId, fields) {
  const cepInput = document.getElementById(cepInputId);
  if (!cepInput) return;

  const statusEl = document.getElementById(cepInputId + '_status');

  function setStatus(msg, tipo) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.className = 'text-xs mt-1 ' + (tipo === 'erro' ? 'text-red-500' : 'text-blue-500');
  }

  cepInput.addEventListener('blur', async function () {
    const cep = this.value.replace(/\D/g, '');
    if (cep.length !== 8) return;

    setStatus('Buscando...', 'info');

    try {
      const res = await fetch('https://viacep.com.br/ws/' + cep + '/json/');
      const data = await res.json();

      if (data.erro) {
        setStatus('CEP não encontrado.', 'erro');
        return;
      }

      const fill = (id, valor) => {
        const el = document.getElementById(id);
        if (el) el.value = valor || '';
      };

      if (fields.logradouro) fill(fields.logradouro, data.logradouro);
      if (fields.bairro)     fill(fields.bairro, data.bairro);
      if (fields.cidade)     fill(fields.cidade, data.localidade);
      if (fields.estado)     fill(fields.estado, data.uf);

      // complemento só preenche se estiver vazio
      if (fields.complemento) {
        const el = document.getElementById(fields.complemento);
        if (el && !el.value) el.value = data.complemento || '';
      }

      setStatus('Endereço preenchido.', 'info');
      setTimeout(() => setStatus('', ''), 3000);

      // foca no campo número após preencher
      if (fields.numero) {
        const el = document.getElementById(fields.numero);
        if (el) el.focus();
      }

    } catch (e) {
      setStatus('Erro ao buscar CEP.', 'erro');
    }
  });
}
