/*
 * Estado da interface, em um unico lugar.
 *
 * Regra de ouro desta camada: o JS guarda estado de tela e renderiza; ele NAO
 * reimplementa regra de negocio. Validacao real, agregacao e qualquer decisao sobre o
 * que extrair continuam no Python (src/webui/api.py), que e quem recebe o payload
 * final. O que existe aqui de "logica" e apenas filtro/map sobre arrays para montar
 * esse payload - equivalente ao que _collect_selection fazia percorrendo BooleanVars.
 */
(function () {
  'use strict';

  const MODES = ['siga', 'nfce', 'nfe'];

  const state = {
    /** Modo ativo: 'siga' | 'nfce' | 'nfe'. */
    mode: 'siga',

    /** true enquanto uma extracao esta rodando (bloqueia disparar outra). */
    running: false,

    /** true depois que o navegador de depuracao abriu com sucesso (SIGA/NFC-e). */
    browserStarted: false,

    /**
     * Grade de empresas, por modo. SIGA e NFC-e mantem listas independentes: sao
     * fluxos diferentes, e o usuario pode ter carregado planilhas distintas em cada
     * um. Cada item: {rowNumber, cod, empresa, cnpj, nfe, nfce, cte, malha, debitos,
     * incluir, chavesCount (so usado no modo NFC-e)}
     */
    rows: { siga: [], nfce: [] },

    /** Rotulo da origem dos dados exibido acima da grade ("Planilha carregada com N..."). */
    sourceLabel: { siga: 'Nenhuma planilha carregada ainda.', nfce: 'Nenhuma empresa carregada ainda.' },

    /**
     * Aba de entrada ativa por modo: 'import' (planilha) ou 'manual' (CNPJs digitados).
     * NFC-e nao tem mais abas (empresas vem do portal) - so SIGA usa isto.
     */
    inputTab: { siga: 'import' },

    /**
     * Tabela de resultados NF-e: Map chaveado pelo caminho da planilha (upsert) +
     * array de ordem de insercao, para as linhas nao "pularem de lugar" conforme os
     * workers terminam fora de ordem. Espelha _nfe_result_vars/_nfe_result_order.
     */
    nfeResults: new Map(),
    nfeResultOrder: [],

    /** Buffer do console. Limitado para uma execucao longa nao crescer sem fim. */
    logLines: [],
  };

  const MAX_LOG_LINES = 2000;

  /** Cria a linha de grade a partir do que o Python devolve em load_spreadsheet. */
  function makeRow(raw) {
    return {
      rowNumber: raw.row_number,
      cod: raw.cod || 'SEM-COD',
      empresa: raw.empresa || 'SEM-EMPRESA',
      cnpj: raw.cnpj || '',
      // Modo NFC-e: quantas chaves de 44 digitos foram encontradas para esta empresa
      // na pasta de chaves configurada (vem de discover_selectable_companies).
      chavesCount: raw.chaves_count || 0,
      // Modo SIGA: um checkbox por tipo de documento, todos marcados ao carregar
      // (mesmo default das BooleanVars da versao Tkinter).
      nfe: true,
      nfce: true,
      cte: true,
      malha: true,
      debitos: true,
      // Modo NFC-e: uma unica coluna "Incluir".
      incluir: true,
    };
  }

  /**
   * Payload do modo SIGA: so entram empresas com pelo menos um documento marcado, e
   * cada uma leva a lista de abas escolhidas. Espelha exatamente o par
   * (selected_rows, selected_tabs_by_row_number) que _collect_selection montava.
   */
  function collectSigaSelection() {
    const selected = [];
    state.rows.siga.forEach((row) => {
      const tabs = [];
      if (row.nfe) tabs.push('NF-e');
      if (row.nfce) tabs.push('NFC-e');
      if (row.cte) tabs.push('CT-e');
      if (row.malha) tabs.push('Malha Fiscal');
      if (row.debitos) tabs.push('Débitos Fiscais');
      if (tabs.length) {
        selected.push({ row_number: row.rowNumber, cod: row.cod, empresa: row.empresa, cnpj: row.cnpj, tabs: tabs });
      }
    });
    return selected;
  }

  /** Payload do modo NFC-e: nao ha escolha por documento, so quem esta marcado. */
  function collectNfceSelection() {
    return state.rows.nfce
      .filter((row) => row.incluir)
      .map((row) => ({ row_number: row.rowNumber, cod: row.cod, empresa: row.empresa, cnpj: row.cnpj }));
  }

  function pushLogLine(entry) {
    state.logLines.push(entry);
    if (state.logLines.length > MAX_LOG_LINES) {
      state.logLines.splice(0, state.logLines.length - MAX_LOG_LINES);
    }
  }

  function resetNfeResults() {
    state.nfeResults = new Map();
    state.nfeResultOrder = [];
  }

  /**
   * Upsert de uma planilha na tabela de resultados: cria na primeira vez que a
   * planilha aparece, atualiza no lugar depois. Devolve true se criou uma linha nova
   * (o render usa isso para decidir entre inserir <tr> ou so mexer nas celulas).
   */
  function upsertNfeResult(result) {
    const key = result.caminho;
    const isNew = !state.nfeResults.has(key);
    if (isNew) state.nfeResultOrder.push(key);
    state.nfeResults.set(key, result);
    return isNew;
  }

  /** "X de Y planilha(s) concluida(s)" do chip de resumo. */
  function nfeSummary() {
    const total = state.nfeResultOrder.length;
    let done = 0;
    state.nfeResults.forEach((r) => {
      if (r.chaves_total > 0 && r.chaves_baixadas + r.chaves_puladas + r.chaves_com_falha >= r.chaves_total) {
        done += 1;
      }
    });
    return { total: total, done: done };
  }

  window.SigaState = {
    MODES: MODES,
    state: state,
    makeRow: makeRow,
    collectSigaSelection: collectSigaSelection,
    collectNfceSelection: collectNfceSelection,
    pushLogLine: pushLogLine,
    resetNfeResults: resetNfeResults,
    upsertNfeResult: upsertNfeResult,
    nfeSummary: nfeSummary,
  };
})();
