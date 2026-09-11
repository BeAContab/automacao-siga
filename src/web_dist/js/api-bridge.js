/*
 * Ponte JS -> Python.
 *
 * Fino de proposito: so encapsula window.pywebview.api, espera a ponte ficar pronta e
 * transforma excecao do Python em erro tratavel aqui. Toda a regra de negocio fica do
 * outro lado (src/webui/api.py).
 */
(function () {
  'use strict';

  /**
   * A ponte do pywebview e injetada de forma assincrona e em duas etapas: primeiro o
   * objeto `window.pywebview.api` passa a existir (vazio) e so depois os metodos do
   * lado Python sao anexados nele. Por isso a condicao de "pronto" NAO pode ser
   * apenas "o objeto api existe" - checar isso resolve cedo demais e a primeira
   * chamada falha com "metodo nao disponivel". Esperamos por um metodo concreto,
   * que so aparece quando a lista completa ja foi injetada.
   */
  const SENTINEL = 'get_initial_state';

  function bridgeReady() {
    return !!(window.pywebview && window.pywebview.api && typeof window.pywebview.api[SENTINEL] === 'function');
  }

  const ready = new Promise((resolve) => {
    if (bridgeReady()) {
      resolve();
      return;
    }
    // O evento 'pywebviewready' e o sinal oficial; o polling cobre o caso de ele ja
    // ter disparado antes deste script rodar.
    window.addEventListener('pywebviewready', () => {
      if (bridgeReady()) resolve();
    }, { once: true });
    const timer = setInterval(() => {
      if (bridgeReady()) {
        clearInterval(timer);
        resolve();
      }
    }, 30);
  });

  async function call(method, ...args) {
    await ready;
    const api = window.pywebview.api;
    if (typeof api[method] !== 'function') {
      throw new Error('Método não disponível na ponte Python: ' + method);
    }
    return api[method](...args);
  }

  window.SigaApi = {
    ready: ready,
    call: call,

    getInitialState: () => call('get_initial_state'),
    onWindowReady: () => call('on_window_ready'),
    reportError: (message, detail) => call('report_client_error', String(message), String(detail || '')),

    // Dialogos nativos (window.create_file_dialog do lado Python).
    pickFile: (kind) => call('pick_file', kind),
    pickDirectory: (kind) => call('pick_directory', kind),

    // Dados
    loadSpreadsheet: (path) => call('load_spreadsheet', path),
    loadManualCnpjs: (text) => call('load_manual_cnpjs', text),
    loadNfceCompanies: (payload) => call('load_nfce_companies', payload),

    // Execucao
    startBrowser: (mode) => call('start_browser', mode),
    startSiga: (payload) => call('start_siga_extraction', payload),
    startNfce: (payload) => call('start_nfce_extraction', payload),
    startNfe: (payload) => call('start_nfe_extraction', payload),
    startChain: (payload) => call('start_chain_extraction', payload),
    pauseExtraction: () => call('pause_extraction'),
    resumeExtraction: () => call('resume_extraction'),
    stopExtraction: () => call('stop_extraction'),
  };
})();
