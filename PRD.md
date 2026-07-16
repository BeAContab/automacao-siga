# PRD - SIGA Automação

## 1. Visão do Produto

O **SIGA Automação** é uma aplicação desktop para Windows destinada a automatizar a extração de documentos fiscais no portal SIGA da Sefaz-CE. O produto reduz trabalho manual repetitivo ao orquestrar navegação autenticada, seleção de CNPJs, solicitação de detalhamentos e download de arquivos fiscais.

O sistema oferece:

- Interface gráfica para operação assistida.
- Entrada de CNPJ por planilha XLSX ou por digitação manual na GUI.
- Processamento de NF-e, NFC-e e CT-e.
- Organização automática dos arquivos por CNPJ, mês e tipo de documento.

## 2. Problema Que o Produto Resolve

O processo manual de acessar o SIGA, localizar cada contribuinte, solicitar relatórios, aguardar disponibilidade e baixar arquivos consome tempo e está sujeito a erro humano.

Este produto resolve esse problema ao:

- Reduzir cliques e navegação repetitiva.
- Padronizar o fluxo de extração.
- Diminuir falhas de seleção e de download.
- Manter rastreabilidade por logs e arquivos de saída.

## 3. Público-Alvo

- Escritórios de contabilidade.
- Departamentos fiscais e financeiros.
- Equipes de backoffice que tratam grandes volumes de CNPJ.
- Operadores que precisam extrair documentos fiscais de forma recorrente.

## 4. Objetivos do Produto

- Automatizar a extração fiscal no SIGA com o menor esforço operacional possível.
- Permitir uso assistido por GUI, sem exigir conhecimento técnico do operador.
- Aceitar entrada por planilha ou por CNPJ manual.
- Reduzir o tempo entre solicitação e download.
- Garantir organização e rastreabilidade dos arquivos gerados.

## 5. Escopo Funcional

### 5.1 Entrada de Dados

- Carregar CNPJs a partir de planilha XLSX.
- Aceitar CNPJs digitados manualmente na GUI.
- Normalizar CNPJs para 14 dígitos.
- Permitir seleção de mês, ano e tipos de documento.

### 5.2 Navegação e Autenticação

- Abrir navegador com perfil dedicado.
- Reutilizar sessão autenticada quando disponível.
- Suportar login manual do usuário.
- Operar com CDP e navegador controlável.

### 5.3 Processamento Fiscal

- Abrir o contribuinte pesquisado.
- Acessar NF-e, NFC-e e CT-e.
- Solicitar resumos e detalhamentos.
- Acionar o botão novo de detalhamento `Baixar Tabela (XLSX)` quando aplicável.
- Preparar as solicitações antes de ir à Central de Downloads.

### 5.4 Downloads

- Varrer a Central de Downloads.
- Priorizar o download mais recente quando houver duplicidade de informação.
- Baixar os itens encontrados em lote.
- Gerar aviso em `.txt` quando um documento ou contribuinte não for localizado.

### 5.5 Saída

- Organizar arquivos por CNPJ, mês e documento.
- Preservar extensão real do arquivo baixado.
- Gerar logs em português.

## 6. Experiência do Usuário

### 6.1 GUI

- O usuário escolhe planilha ou entrada manual.
- Seleciona mês, ano, pasta de saída e documentos.
- Inicia o navegador e faz login.
- Executa o processamento e acompanha o log na tela.

## 7. Requisitos Funcionais

1. O sistema deve aceitar pelo menos um CNPJ para execução.
2. O sistema deve permitir processamento via planilha XLSX.
3. O sistema deve permitir entrada manual de CNPJs na GUI.
4. O sistema deve permitir seleção de NF-e, NFC-e e CT-e.
5. O sistema deve abrir navegador e permitir autenticação manual.
6. O sistema deve reutilizar sessão autenticada quando possível.
7. O sistema deve solicitar documentos no SIGA e depois baixar os arquivos encontrados.
8. O sistema deve gerar `.txt` quando um CNPJ ou download não for localizado.
9. O sistema deve manter logs de execução em português.
10. O sistema deve gerar saída organizada por estrutura de pastas previsível.

## 8. Requisitos Não Funcionais

- Executar em Windows.
- Operar localmente, sem dependência de servidor externo do produto.
- Ser compatível com empacotamento em `.exe`.
- Manter tolerância a mudanças de layout do SIGA por meio de seletores e fallbacks.
- Preservar confidencialidade do material processado.
- Ser auditável por logs e arquivos de aviso.

## 9. Limitações Conhecidas

- A automação depende do layout e do comportamento atual do SIGA.
- Mudanças no site podem exigir ajustes de seletor e tempo de espera.
- O uso de certificado digital e políticas do navegador depende do ambiente do usuário.
- A qualidade da extração depende da disponibilidade dos dados no portal.

## 10. Métricas De Sucesso

- Redução do tempo de processamento por lote.
- Redução de falhas por intervenção manual.
- Percentual de downloads concluídos com sucesso.
- Percentual de CNPJs identificados corretamente.
- Quantidade de avisos `.txt` gerados quando não houver correspondência.

## 11. Critérios De Aceite

- Um operador consegue rodar a GUI sem conhecer o backend.
- Um lote com múltiplos CNPJs é processado até o final sem falha por um único CNPJ ausente.
- CNPJs não encontrados geram aviso e o fluxo continua.
- O instalador consegue distribuir o executável da GUI.
- Os arquivos baixados ficam organizados e rastreáveis.

## 12. Fora De Escopo

- Suporte a outros portais fiscais fora do SIGA.
- Execução em Linux ou macOS.
- Sincronização com banco de dados central.
- Multiusuário em tempo real.
- API pública para integração externa.
- Modo de lote via terminal/linha de comando (descontinuado; a GUI é a única interface de extração suportada). O modo assistido via terminal (`--live-assist`) segue disponível apenas como ferramenta de depuração interna.

## 13. Riscos

- Mudanças frequentes no layout do SIGA.
- Tempo de resposta imprevisível da Central de Downloads.
- Dependência de navegador e certificado no ambiente do usuário.
- Divergência entre o arquivo baixado e o nome esperado pelo fluxo.

## 14. Oportunidades Futuras

- Perfis de processamento salvos por cliente.
- Histórico de execuções com relatório consolidado.
- Modo de reprocessamento de itens com falha.
- Melhorias de desempenho na fila de downloads.
- Tabela de preços e licenciamento comercial por assinatura.

