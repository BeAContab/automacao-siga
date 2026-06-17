# 🚀 SIGA Automação

**Otimize seu tempo e elimine o trabalho manual na extração de arquivos fiscais.**

O **SIGA Automação** é uma solução corporativa de alta performance desenvolvida para interagir com o portal SIGA (Sefaz-CE). Com ele, você automatiza a extração em lote de documentos fiscais (NF-e, NFC-e e CT-e) a partir de uma lista de empresas, trazendo eficiência, segurança e confiabilidade para a sua rotina contábil e fiscal.

---

## 🌟 Principais Benefícios

- **Ganho de Produtividade:** Elimina horas de navegação repetitiva e cliques manuais.
- **Precisão e Confiabilidade:** Reduz drasticamente o erro humano na seleção e download de arquivos XML/PDF.
- **Integração Perfeita:** Funciona a partir de planilhas `.xlsx` padronizadas, extraindo arquivos automaticamente para pastas organizadas por `COD - EMPRESA - CNPJ`, mês e tipo de documento.
- **Flexibilidade de Interface:** Oferece tanto uma Interface Gráfica (GUI) intuitiva para usuários de negócio, quanto uma Interface de Linha de Comando (CLI) para integrações e uso avançado.
- **Segurança de Dados:** Mantém o controle total no ambiente local do usuário, utilizando perfis dedicados de navegador e respeitando as políticas de segurança corporativas.

---

## 💻 Funcionalidades em Destaque

- **Automação Inteligente:** Reaproveitamento de sessões já autenticadas do navegador para evitar múltiplos logins.
- **Gestão de Certificados:** Configuração automatizada para lidar com certificados digitais A1/A3 sem fricção no Windows.
- **Execução Seletiva:** Escolha quais tipos de documentos (NF-e, NFC-e, CT-e) e quais meses/anos deseja processar em uma única rodada.
- **Logs e Rastreabilidade:** Registro detalhado de cada ação do robô (`run.log`) e capturas de erros (`errors.log`).

---

## 🛠️ Como Utilizar

### 1. Preparação dos Dados
Crie ou edite a planilha de entrada chamada `cnpj.xlsx`.
*Nota: Os CNPJs devem ser preservados com 14 dígitos, incluindo zeros à esquerda.*
*Layout recomendado: colunas `COD`, `EMPRESA` e `CNPJ`.*

### 2. Interface Gráfica (Recomendado)
A forma mais amigável de utilizar o sistema. A GUI foi organizada no estilo de dashboard corporativo do `design-model`, permitindo carregar planilhas, inserir CNPJs manualmente, selecionar diretórios de saída e visualizar logs em tempo real. O botão **Ajuda** abre um pop-up com o passo a passo de uso.

```powershell
.\.venv\Scripts\python.exe .\main.py --gui
# Ou caso esteja usando o executável:
.\dist\siga-automacao-gui.exe
```

**Passo a passo na GUI:**
1. Carregue sua planilha `cnpj.xlsx` ou use a aba **Entrada Manual** para colar os CNPJs.
2. Clique em **Carregar CNPJs manuais** se preferir usar a entrada digitada.
3. Ajuste mês, ano, documentos e pasta de saída no painel lateral.
4. Clique em **Iniciar Navegador** e realize o login manual no portal do SIGA.
5. Após o login concluído, clique em **Executar Extração** para iniciar as extrações.

### 3. Modo Terminal / CLI
Para operações rápidas ou integrações. O terminal guiará você por parâmetros como Mês, Ano e Documentos desejados.

```powershell
# Execução iterativa (o robô fará as perguntas no terminal)
.\.venv\Scripts\python.exe .\main.py

# Execução parametrizada direta
.\.venv\Scripts\python.exe .\main.py --month Maio --year 2026 --spreadsheet .\cnpj.xlsx --docs NF-e CT-e
```

---

## ⚙️ Configurações Avançadas de Sistema

### Organização dos Arquivos Gerados
Os downloads são estruturados automaticamente no seguinte formato:
`<pasta-escolhida>/<COD - EMPRESA - CNPJ>/<mes>/<documento>/`
*Dica de validação: Compare as saídas geradas com `testes.csv`, que serve de referência manual para extração de NFC-e/Emissor.*

### Certificados Digitais
A automação cria um perfil isolado do navegador, contornando bloqueios de segurança recentes, e configura políticas locais para selecionar o certificado do usuário silenciosamente.
- **Ignorar política de certificado:** `--skip-certificate-policy`
- **Remover política local gerada:** `--clear-certificate-policy`
- **Usar perfil padrão do sistema:** `--system-browser-profile`
- **Forçar encerramento de processos antes de rodar:** `--force-restart-browser`

### Reaproveitamento de Sessão Web
Por padrão, o sistema tenta usar uma aba já autenticada no SIGA (`https://siga.sefaz.ce.gov.br/ui/`) para acelerar o processo sem precisar repetir a etapa de certificado/recaptcha.
- Para desativar esse comportamento no terminal: `--disable-attach`
- Via `.env`: defina `PREFER_EXISTING_SIGA_SESSION=false`

### Modo Assistido (Live Assist)
Disponível para diagnóstico acompanhando a sessão do Selenium visualmente:
```powershell
.\.venv\Scripts\python.exe .\main.py --live-assist
```

---

## 📦 Compilação e Distribuição

A solução pode ser empacotada em arquivos `.exe` independentes, dispensando a instalação do Python nas máquinas dos usuários finais.

**Gerar executável completo (CLI + GUI):**
```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean siga-automacao.spec
```

**Gerar executável exclusivo com Interface Gráfica:**
```powershell
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean siga-automacao-gui.spec
```

**Gerar o Instalador (Inno Setup):**
Abra o arquivo `installer\siga-automacao.iss` no Inno Setup Compiler e clique em **Compile** (ou `Ctrl+F9`). O instalador final (`SIGA-Automacao-Setup.exe`) será gerado na pasta `dist\installer\`, pronto para distribuição sem exigir privilégios de administrador.

---

## 🔒 Licenciamento e Propriedade

**Copyright © 2026 Barreira & Associados. Todos os direitos reservados.**

Este software é de propriedade privada e confidencial. O uso deste projeto é restrito exclusivamente às pessoas, empresas ou equipes autorizadas pelo proprietário. Consulte o arquivo `LICENSE` na raiz do projeto para mais detalhes. Arquivos sensíveis e a pasta de base de conhecimento (`brain/`) ficam protegidos fora do controle de versão.
