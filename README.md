# SIGA Automacao

Automacao por terminal com Selenium para acessar o SIGA, aguardar login manual e extrair os arquivos fiscais por CNPJ a partir de uma planilha `.xlsx`.

## Entrada e saida

- Planilha de entrada: `cnpj.xlsx`
- CNPJs preservados com 14 digitos, inclusive zeros a esquerda
- Saida organizada em `saida/<cnpj>/<mes>/<documento>/`
- Logs em `logs/`
- Notas de contexto e decisoes em `brain/`

## Uso

Execute o fluxo interativo:

```powershell
.\.venv\Scripts\python.exe .\main.py
```

Ou informe os parametros diretamente:

```powershell
.\.venv\Scripts\python.exe .\main.py --month Maio --year 2026 --spreadsheet .\cnpj.xlsx
```

Para executar multiplos meses na mesma execucao:

```powershell
.\.venv\Scripts\python.exe .\main.py --month Maio Junho --year 2026 --docs NF-e CT-e
```

Para escolher quais documentos processar:

```powershell
.\.venv\Scripts\python.exe .\main.py --month Maio --year 2026 --docs NF-e CT-e
```

O terminal vai:

1. pedir o(s) mes(es) de referencia, se nao informado;
2. pedir o ano de referencia, se nao informado;
3. pedir quais documentos executar (NF-e, NFC-e, CT-e ou todos), se nao informado;
4. pedir a planilha `.xlsx`, se nao informada;
5. tentar reaproveitar uma aba do SIGA ja autenticada em um Chrome com CDP ativo;
6. se nao encontrar uma aba valida, abrir o Chrome em um perfil dedicado de automacao para login manual;
7. aguardar `Enter` antes de anexar o Selenium, somente apos o SIGA estar autenticado;
8. conectar o Selenium ao navegador ja autenticado;
9. executar a extracao no mesmo contexto autenticado.

Para validar a saida esperada, voce pode comparar os arquivos gerados com `testes.csv`, que serve como referencia manual para a extração de NFC-e/Emissor.

O Selenium se conecta ao Chrome/Edge pela porta de depuracao somente depois do login manual, para manter a mesma sessao sem controlar a etapa do certificado/recaptcha.

## Certificado digital

O navegador e aberto em um perfil dedicado de automacao com CDP ativo. No Windows, a selecao de `Seu certificado digital` usa os certificados instalados no repositario do usuario do Windows.

Esse perfil dedicado evita bloqueios recentes do Chrome ao usar `--remote-debugging-port` com o perfil normal do usuario.

Antes de abrir o navegador, o programa configura a politica local do Chrome/Edge para selecionar automaticamente o certificado de cliente instalado no usuario atual para os dominios do SIGA e SSO.

Para executar sem alterar a politica de certificado:

```powershell
.\.venv\Scripts\python.exe .\main.py --skip-certificate-policy
```

Para remover a politica criada pelo programa:

```powershell
.\.venv\Scripts\python.exe .\main.py --clear-certificate-policy
```

Se o Windows bloquear a gravacao automatica da politica, o programa gera o arquivo `logs/chrome-certificate-policy.reg`. Nesse caso, aplique o arquivo manualmente com uma conta que tenha permissao para alterar politicas do Chrome.

Se quiser tentar usar o perfil normal do Chrome:

```powershell
.\.venv\Scripts\python.exe .\main.py --system-browser-profile
```

Se seus certificados estiverem em outro perfil do Chrome:

```powershell
.\.venv\Scripts\python.exe .\main.py --chrome-profile-directory "Profile 1"
```

Se quiser encerrar os processos existentes do Chrome antes de iniciar a automacao:

```powershell
.\.venv\Scripts\python.exe .\main.py --force-restart-browser
```

## Reaproveitamento de sessao

Se existir um Chrome com CDP ativo e uma aba em `https://siga.sefaz.ce.gov.br/ui/` ja autenticada, a automacao tenta se anexar a essa aba antes de pedir login manual.

Para desabilitar esse comportamento em uma execucao especifica:

```powershell
.\.venv\Scripts\python.exe .\main.py --disable-attach
```

Para desabilitar por configuracao:

```env
PREFER_EXISTING_SIGA_SESSION=false
```

## Live assist

O modo assistido continua disponivel para diagnostico usando a mesma sessao Selenium:

```powershell
.\.venv\Scripts\python.exe .\main.py --live-assist
```

## Logs

- Execucao geral: `logs/run.log`
- Erros: `logs/errors.log`

Arquivos locais sensiveis, certificados, logs, saidas e a pasta `brain/` ficam fora do controle de versao via `.gitignore`.
