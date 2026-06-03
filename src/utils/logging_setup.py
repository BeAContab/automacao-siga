from __future__ import annotations

"""Configuração central de logs para execução, erro e exceções globais."""

import logging
import sys
import threading
from pathlib import Path


def configure_logging(log_file: Path) -> None:
    """Ativa logs em arquivo e no console com tratamento consistente de erros."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    error_log_file = log_file.parent / "errors.log"

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    run_file_handler = logging.FileHandler(log_file, encoding="utf-8")
    run_file_handler.setLevel(logging.INFO)
    run_file_handler.setFormatter(formatter)

    error_file_handler = logging.FileHandler(error_log_file, encoding="utf-8")
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    root_logger.addHandler(run_file_handler)
    root_logger.addHandler(error_file_handler)
    root_logger.addHandler(stream_handler)

    install_global_exception_logging()


def install_global_exception_logging() -> None:
    """Registra exceções não tratadas em nível global e em threads."""
    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        # Erros de teclado seguem o comportamento normal do terminal.
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.getLogger("global").error(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        # Falhas em threads também precisam aparecer no log principal para diagnóstico.
        if args.exc_type and issubclass(args.exc_type, KeyboardInterrupt):
            return
        logging.getLogger("global").error(
            "Unhandled thread exception in %s",
            args.thread.name if args.thread else "unknown-thread",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception
