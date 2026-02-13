"""
Centralized logging configuration for AaltoHub v2.

Provides structured logging with:
- JSON format in production (parseable by log aggregators)
- Human-readable format in development
- RotatingFileHandler for persistent logs (50MB per file, 5 backups = 250MB max)
- Console output to stdout (captured by systemd journal)

Usage:
    from app.logging_config import setup_logging
    from app.config import settings

    setup_logging(settings, service_name="api")  # or "crawler"
"""
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from app.config import Settings


def setup_logging(settings: Settings, service_name: str = "api") -> None:
    """Configure application logging with file rotation and structured output.

    Args:
        settings: Application settings containing LOG_LEVEL and ENVIRONMENT
        service_name: Service identifier for log filenames ("api" or "crawler")

    Sets up:
        - RotatingFileHandler: 50MB per file, 5 backups (250MB total)
        - StreamHandler: stdout (captured by systemd journal)
        - JSON format in production, human-readable in development
    """
    # Determine log directory based on environment
    if settings.ENVIRONMENT == "production":
        log_dir = Path("/home/ubuntu/AALTOHUBv2/logs")
    else:
        log_dir = Path(__file__).parent.parent / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)

    # Log file path
    log_file = log_dir / f"{service_name}.log"

    # Create handlers
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=50 * 1024 * 1024,  # 50MB per file
        backupCount=5,               # Keep 5 backups (250MB total)
        encoding="utf-8",
    )

    console_handler = logging.StreamHandler()

    # Configure formatters based on environment
    if settings.ENVIRONMENT != "development":
        # Production: structured JSON logging
        try:
            from pythonjsonlogger import jsonlogger

            json_formatter = jsonlogger.JsonFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={
                    "asctime": "timestamp",
                    "levelname": "level",
                    "name": "logger",
                },
            )
            file_handler.setFormatter(json_formatter)
            console_handler.setFormatter(json_formatter)

        except ImportError:
            # Fallback if pythonjsonlogger not installed
            text_formatter = logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
            file_handler.setFormatter(text_formatter)
            console_handler.setFormatter(text_formatter)

    else:
        # Development: human-readable format
        text_formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        file_handler.setFormatter(text_formatter)
        console_handler.setFormatter(text_formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL.upper())

    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Add handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Log initialization message
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging initialized: service={service_name}, "
        f"level={settings.LOG_LEVEL}, "
        f"environment={settings.ENVIRONMENT}, "
        f"log_file={log_file}"
    )
