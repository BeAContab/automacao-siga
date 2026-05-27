# SIGA Automacao

Automacao por terminal para acessar o SIGA, aguardar login manual e extrair os arquivos fiscais por CGF a partir de uma planilha `.xlsx`.

## Uso

Execute o fluxo interativo:

```powershell
.\.venv\Scripts\python.exe .\main.py
```

Ou informe os parametros diretamente:

```powershell
.\.venv\Scripts\python.exe .\main.py --month Maio --spreadsheet .\cgf.xlsx
```

O terminal vai:

1. pedir o mes de referencia, se nao informado;
2. pedir a planilha `.xlsx`, se nao informada;
3. abrir o navegador para login manual;
4. aguardar `Enter` apos o login;
5. executar a extracao no mesmo contexto autenticado.

## Live assist

O modo assistido continua disponivel para diagnostico:

```powershell
.\.venv\Scripts\python.exe .\main.py --live-assist
```

## Logs

- Execucao geral: `logs/run.log`
- Erros: `logs/errors.log`

Arquivos locais sensiveis, certificados, logs, saidas e a pasta `brain/` ficam fora do controle de versao via `.gitignore`.
# automacao-siga
