# SIGA Automação

**Fechamento fiscal mensal em minutos, não em dias.**

O **SIGA Automação** é a solução corporativa que elimina o trabalho manual e repetitivo de extrair documentos fiscais do portal SIGA da Secretaria da Fazenda do Estado do Ceará (SEFAZ-CE). Em vez de abrir contribuinte por contribuinte, aba por aba, o operador importa uma planilha de CNPJs, faz login uma única vez e a ferramenta assume toda a navegação — solicitando, localizando e baixando cada relatório automaticamente.

Resultado: o que antes consumia horas de um colaborador clicando no portal passa a rodar sozinho, com log detalhado de cada etapa e organização automática dos arquivos por empresa.

---

## Por que o SIGA Automação

* **Tempo de volta para a operação:** um lote de dezenas de CNPJs, que levaria um dia inteiro de trabalho manual, roda em background enquanto a equipe cuida de análise e conferência.
* **Menos erro humano:** a extração segue sempre o mesmo caminho, sem risco de esquecer um CNPJ, baixar o mês errado ou perder um relatório no meio do processo.
* **Visibilidade total:** console de log em tempo real narra cada ação em português simples — o operador sabe exatamente o que está acontecendo a qualquer momento, sem precisar interpretar logs técnicos.
* **Feito sob medida para escritórios de contabilidade:** organização de saída já no padrão que a equipe fiscal usa (`COD - EMPRESA - CNPJ`), pronta para conferência ou importação em outros sistemas.

## Principais Funcionalidades

* **Extração inteligente em lote:** processa múltiplos contribuintes de forma sequencial a partir de uma única planilha de trabalho, sem intervenção manual entre um CNPJ e outro.
* **Cobertura completa de documentos fiscais:** Notas Fiscais Eletrônicas (NF-e), Notas Fiscais de Consumidor Eletrônicas (NFC-e), Conhecimentos de Transporte Eletrônicos (CT-e), além dos relatórios especiais de **Malha Fiscal** (indícios de irregularidades) e **Débitos Fiscais**.
* **Importação flexível:** planilha Excel por arrastar-e-soltar direto na interface, ou preenchimento manual dos dados quando necessário.
* **Login seguro e assistido:** o navegador é controlado pela automação, mas o login continua sendo feito manualmente pelo operador — inclusive com certificado digital A1 — sem que credenciais passem pela ferramenta.
* **Organização automática da saída:** cada arquivo baixado é classificado em pastas por código interno, nome da empresa e CNPJ, prontas para conferência ou envio.
* **Console de log em tempo real:** cada etapa da automação é narrada em linguagem simples, com destaque visual para sucessos, alertas e falhas — sem necessidade de conhecimento técnico para acompanhar a execução.
* **Resiliência a instabilidades do portal:** retentativas automáticas diante de lentidão, sobrecarga ou indisponibilidade momentânea do SIGA, e reconhecimento automático de CNPJs sem cadastro ativo, para que um problema pontual não interrompa o lote inteiro.
* **Central de Ajuda integrada:** manual de instruções acessível direto pela interface, sem depender de suporte técnico para dúvidas do dia a dia.

## Público-Alvo

* **Escritórios de Contabilidade e Assessoria:** que atendem dezenas ou centenas de clientes e precisam de um processo padronizado de fechamento fiscal mensal.
* **Departamentos Fiscais Corporativos:** que precisam de exatidão e agilidade na auditoria interna de entradas e saídas.
* **Equipes de Controladoria e Backoffice:** que buscam reduzir a sobrecarga operacional e eliminar erros de digitação e consulta manual repetitiva.

## Como Funciona

1. **Defina o escopo:** importe a planilha com os CNPJs (arrastando o arquivo para a interface) ou digite os dados diretamente no painel.
2. **Selecione o período e os documentos:** escolha mês, ano e quais tipos de documento fiscal deseja consultar.
3. **Faça login uma única vez:** o navegador integrado abre o portal SIGA para que você entre com suas credenciais ou certificado digital.
4. **Acompanhe a execução:** a partir daí, a automação navega pelo portal, solicita os relatórios, aguarda o processamento e baixa cada arquivo — tudo narrado em tempo real no console da interface.

---

## Licenciamento

Copyright © 2026 Barreira & Associados. Todos os direitos reservados.

Este software é de propriedade privada e confidencial. O uso deste projeto é restrito exclusivamente às pessoas, empresas ou equipes autorizadas pelo proprietário. Consulte o arquivo `LICENSE` na raiz do projeto para mais detalhes.
