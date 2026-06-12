function maskCNPJ(v) {
  return v.replace(/\D/g, '')
    .replace(/(\d{2})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d)/, '$1/$2')
    .replace(/(\d{4})(\d{1,2})/, '$1-$2')
    .slice(0, 18);
}

function maskCPF(v) {
  return v.replace(/\D/g, '')
    .replace(/(\d{3})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d)/, '$1.$2')
    .replace(/(\d{3})(\d{1,2})/, '$1-$2')
    .slice(0, 14);
}

function maskPhone(v) {
  const digits = v.replace(/\D/g, '').slice(0, 11);
  if (digits.length <= 10) {
    return digits
      .replace(/(\d{2})(\d)/, '($1) $2')
      .replace(/(\d{4})(\d)/, '$1-$2');
  }
  return digits
    .replace(/(\d{2})(\d)/, '($1) $2')
    .replace(/(\d{5})(\d)/, '$1-$2');
}

function maskCEP(v) {
  return v.replace(/\D/g, '')
    .replace(/(\d{5})(\d{1,3})/, '$1-$2')
    .slice(0, 9);
}

function maskCurrency(v) {
  const digits = v.replace(/\D/g, '');
  if (!digits) return '';
  const num = (parseInt(digits, 10) / 100).toFixed(2);
  return 'R$ ' + num.replace('.', ',').replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

function currencyToDecimal(v) {
  return v.replace('R$', '').replace(/\./g, '').replace(',', '.').trim();
}

function initMasks() {
  document.querySelectorAll('[data-mask]').forEach(function (el) {
    const type = el.dataset.mask;

    const applyFn = {
      cnpj:     maskCNPJ,
      cpf:      maskCPF,
      phone:    maskPhone,
      currency: maskCurrency,
      cep:      maskCEP,
    }[type];

    if (!applyFn) return;

    el.addEventListener('input', function () {
      const pos = this.selectionStart;
      const prev = this.value.length;
      this.value = applyFn(this.value);
      const delta = this.value.length - prev;
      this.setSelectionRange(pos + delta, pos + delta);
    });

    // para campos de valor: converte para decimal limpo antes de enviar
    if (type === 'currency') {
      el.closest('form')?.addEventListener('submit', function () {
        el.value = currencyToDecimal(el.value);
      }, { once: false });
    }
  });
}

document.addEventListener('DOMContentLoaded', initMasks);
