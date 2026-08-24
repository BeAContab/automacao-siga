/*
 * Modais de aviso/erro/confirmacao.
 *
 * Substituem os ~20 messagebox.showwarning/showerror/showinfo/askyesno da versao
 * Tkinter: o pywebview nao tem um equivalente nativo de caixa de mensagem para esses
 * casos (so tem create_confirmation_dialog, usado no fechamento da janela, que roda do
 * lado Python). Aqui tudo e HTML/JS, com o mesmo texto e o mesmo papel de antes.
 */
(function () {
  'use strict';

  const overlay = document.getElementById('modal-overlay');
  const iconEl = document.getElementById('modal-icon');
  const titleEl = document.getElementById('modal-title');
  const messageEl = document.getElementById('modal-message');
  const okBtn = document.getElementById('modal-ok');
  const cancelBtn = document.getElementById('modal-cancel');

  // Cor/icone por nivel, para o usuario reconhecer a gravidade sem ler tudo.
  const LEVELS = {
    info: { icon: 'info', cls: 'text-secondary' },
    success: { icon: 'check_circle', cls: 'text-status-green' },
    warning: { icon: 'warning', cls: 'text-status-orange' },
    error: { icon: 'error', cls: 'text-error' },
    question: { icon: 'help', cls: 'text-secondary' },
  };

  let resolver = null;

  function close(value) {
    overlay.classList.add('hidden');
    overlay.classList.remove('flex');
    const done = resolver;
    resolver = null;
    if (done) done(value);
  }

  function open(options) {
    const level = LEVELS[options.level] || LEVELS.info;
    iconEl.textContent = level.icon;
    iconEl.className = 'material-symbols-outlined text-[28px] shrink-0 ' + level.cls;
    titleEl.textContent = options.title || 'SIGA Automação';
    messageEl.textContent = options.message || '';
    okBtn.textContent = options.okLabel || 'OK';
    cancelBtn.textContent = options.cancelLabel || 'Cancelar';
    cancelBtn.classList.toggle('hidden', !options.withCancel);

    overlay.classList.remove('hidden');
    overlay.classList.add('flex');
    okBtn.focus();

    return new Promise((resolve) => {
      resolver = resolve;
    });
  }

  okBtn.addEventListener('click', () => close(true));
  cancelBtn.addEventListener('click', () => close(false));

  // Esc cancela; Enter confirma. Um app desktop precisa responder ao teclado.
  document.addEventListener('keydown', (event) => {
    if (overlay.classList.contains('hidden')) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      close(false);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      close(true);
    }
  });

  // Clicar fora fecha (equivale a cancelar).
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) close(false);
  });

  window.SigaModal = {
    /** Aviso simples com um unico botao. Devolve Promise<true>. */
    alert: function (message, level, title) {
      return open({ message: message, level: level || 'info', title: title });
    },
    /** Confirmacao com OK/Cancelar. Devolve Promise<boolean>. */
    confirm: function (message, options) {
      const opts = options || {};
      return open({
        message: message,
        level: opts.level || 'question',
        title: opts.title,
        withCancel: true,
        okLabel: opts.okLabel,
        cancelLabel: opts.cancelLabel,
      });
    },
    isOpen: function () {
      return !overlay.classList.contains('hidden');
    },
  };
})();
