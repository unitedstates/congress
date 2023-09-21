import logging

from congress.utils.logs.setup import default_handlers, setup_logging

project_logger = setup_logging(
    name=__name__,
    handlers=default_handlers(log_level=logging.INFO),
)
