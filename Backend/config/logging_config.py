import json
import logging
from datetime import datetime, timezone
from contextvars import ContextVar


# Stores the request ID for the current request.
request_id_var = ContextVar("request_id", default=None)


class JsonFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord) -> str:

        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request ID if available.
        request_id = request_id_var.get()

        if request_id:
            log_data["request_id"] = request_id

        # Include only explicitly allowed extra fields.
        allowed_fields = [
            "method",
            "path",
            "status_code",
            "duration_ms",
        ]

        for field in allowed_fields:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        # Include exception details when available.
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)

def configure_logging():

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Avoid adding duplicate handlers if configuration runs again.
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
