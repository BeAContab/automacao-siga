import sys
import time
import logging
from pathlib import Path

# Adiciona o diretório raiz do projeto ao sys.path para o Python localizar a pasta 'src'
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import Settings
from src.extraction.spreadsheet import load_cnpjs_from_xlsx
from src.auth.siga_login import SigaLoginFlow
from src.utils.browser import BrowserSession
from src.extraction.siga_extractor import SigaContributorExtractor, TaxpayerNotFoundError

# Configuração do log em tempo real para arquivo txt
log_path = Path(r"c:\Users\gabriel.lima\Documents\GitHub\automacao-siga\testes\live_test_log.txt")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_path, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
LOGGER = logging.getLogger(__name__)

def main():
    settings = Settings(
        output_dir=Path(r"c:\Users\gabriel.lima\Documents\GitHub\automacao-siga\downloads"),
        timeout_ms=15000,
        headless=False
    )
    
    excel_path = Path(r"c:\Users\gabriel.lima\Documents\GitHub\automacao-siga\testes\teste.xlsx")
    
    print("Carregando planilhas...")
    rows = load_cnpjs_from_xlsx(excel_path)
    
    print("Iniciando navegador...")
    
    # Igual a aplicação real: inicializa o Chrome puro via subprocess ANTES de conectar o WebDriver,
    # caso contrário o WebDriver passa flags que quebram a seleção do certificado A1/A3.
    from src.utils.browser import get_connect_browser_url, launch_debug_browser
    if not settings.connect_browser_url:
        settings.connect_browser_url = get_connect_browser_url(settings)
    launch_debug_browser(settings)
    
    print("\n" + "="*50)
    print("NAVEGADOR ABERTO. POR FAVOR, FAÇA O LOGIN NO SIGA.")
    print("="*50 + "\n")
    
    # IMPORTANTE: Esperar o login ANTES de conectar o Selenium (BrowserSession).
    # Na aplicação real (GUI), o Selenium só conecta quando o usuário clica em "Executar".
    input("Pressione ENTER aqui no terminal assim que concluir o login no navegador... ")
    
    with BrowserSession(settings) as context:
        flow = SigaLoginFlow(settings)
        page = flow.confirm_authenticated_context(context, browser=context.browser)
        
        extractor = SigaContributorExtractor(settings, allow_manual_login_prompt=False)
        
        for row in rows:
            print(f"\nProcessando CNPJ: {row.cnpj}")
            try:
                # Tentamos abrir o contribuinte
                extractor._open_taxpayer_from_home(page, row.cnpj)
                
                # Se abrir, extrai NF-e e NFC-e
                results = extractor._extract_fiscal_tables(
                    page=page,
                    cgf=row.cnpj,
                    month_reference="Junho", # Ajustado para "Junho" (mês 06) conforme esperado pela automação
                    reference_year="2026",
                    taxpayer_folder_name=row.cnpj,
                    selected_tabs=["NF-e", "NFC-e"],
                    row_number=row.row_number
                )
                print(f"Sucesso. {len(results)} solicitacoes feitas para {row.cnpj}.")
                
            except TaxpayerNotFoundError as exc:
                print("\n" + "!"*50)
                print(f"ATENCAO: Contribuinte não localizado: {row.cnpj}")
                print(f"Motivo: {exc}")
                print("A AUTOMACAO ESTA PAUSADA. Verifique o navegador.")
                print("!"*50 + "\n")
                input(">>> Pressione ENTER para continuar com o proximo CNPJ... ")
                
            except Exception as e:
                print(f"Erro inesperado no CNPJ {row.cnpj}: {e}")
                
        print("\nTeste concluido.")

if __name__ == "__main__":
    main()
