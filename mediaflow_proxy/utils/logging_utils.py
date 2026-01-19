import logging
import sys
from pythonjsonlogger import jsonlogger
from mediaflow_proxy.configs import settings
from mediaflow_proxy.middleware.request_id import get_request_id

class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        request_id = get_request_id()
        if request_id:
            log_record['request_id'] = request_id
        if not log_record.get('timestamp'):
            # this doesn't use record.created, so it is slightly off
            import datetime
            now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            log_record['timestamp'] = now
        if log_record.get('level'):
            log_record['level'] = log_record['level'].upper()
        else:
            log_record['level'] = record.levelname

def setup_logging():
    """
    Configure the logging for the application.
    """
    log_level = settings.log_level.upper()
    
    logger = logging.getLogger()
    logger.setLevel(log_level)

    handler = logging.StreamHandler(sys.stdout)
    formatter = CustomJsonFormatter('%(timestamp)s %(level)s %(name)s %(message)s')
    handler.setFormatter(formatter)
    
    # Remove existing handlers to avoid duplicates
    logger.handlers = []
    logger.addHandler(handler)
    
    # Set levels for third-party libraries to avoid noise
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    # logging.getLogger("uvicorn.access").disabled = True # Disable default access log to avoid duplication if we log requests manually, or just let it be json.
    
    # Re-enable uvicorn access but set to parent logger
    # Actually, uvicorn configures its own loggers. We might want to override them.
    # For now, let's keep it simple.
    
    return logger

