import logging
import sys
from datetime import datetime
import json
import os
from logging.handlers import RotatingFileHandler


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record):
        log_record = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'process_id': record.process,
            'thread_id': record.thread,
        }

        if record.exc_info:
            log_record['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_record, ensure_ascii=False)

def setup_logger(name, log_file=None, level=logging.INFO):
    """Setup logger with file and console handlers"""
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler - simplified for Windows
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler with rotation + optional structured JSON format
    os.makedirs('logs', exist_ok=True)
    resolved_log_file = log_file or 'logs/bot.log'
    max_bytes = int(os.getenv('LOG_MAX_BYTES', str(10 * 1024 * 1024)))  # 10MB
    backup_count = int(os.getenv('LOG_BACKUP_COUNT', '5'))
    log_format = os.getenv('LOG_FORMAT', 'json').lower()

    file_handler = RotatingFileHandler(
        resolved_log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    if log_format == 'json':
        file_handler.setFormatter(JsonFormatter())
    else:
        file_handler.setFormatter(console_formatter)
    logger.addHandler(file_handler)
    
    return logger

def log_trade(action, data, log_file='logs/trades.jsonl'):
    """Log trade activity to JSONL file"""
    try:
        with open(log_file, 'a') as f:
            log_entry = {
                'timestamp': datetime.utcnow().isoformat(),
                'action': action,
                **data
            }
            f.write(json.dumps(log_entry) + '\n')
    except Exception as e:
        logging.error(f"Failed to log trade: {e}")
