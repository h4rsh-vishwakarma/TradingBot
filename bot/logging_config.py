import logging

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("bot.log"),  # Requirement: Log to a file
            logging.StreamHandler()         # Also print to console
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()