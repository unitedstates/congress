import os

import enum


class CongressConstants(enum.Enum):
    """Constants for united-states-congress."""

    LOG_FORMAT = os.environ.get(
        'CONGRESS_LOG_FORMAT',
        '%(asctime)s | %(levelname)-8s | %(pathname)s:%(lineno)s | %(funcName)s | %(message)s',
    )
    LOG_OUTPUT_FOLDER = os.environ.get(
        'CONGRESS_LOG_OUTPUT_FOLDER',
        'logs',
    )
    LOG_FILE_BASE_NAME = os.environ.get(
        'CONGRESS_LOG_FILE_BASE_NAME',
        'congress_standalone',
    )
    LOG_FILE_INTERVAL_TYPE = os.environ.get(
        'CONGRESS_LOG_FILE_INTERVAL_TYPE',
        'midnight',
    )
    LOG_FILE_INTERVAL = int(
        os.environ.get(
            'CONGRESS_LOG_FILE_INTERVAL',
            1,
        )
    )
    DATA_FOLDER_FILEPATH = os.environ.get(
        'CONGRESS_DATA_FOLDER_FILEPATH',
        'data',
    )
    CACHE_FOLDER_FILEPATH = os.environ.get(
        'CONGRESS_CACHE_FOLDER_FILEPATH',
        'cache',
    )
    CONGRESS_DEFAULT_LOGGER_NAME = 'congress.utils.logs.log'
    LOG_ARCHIVES_MAX_AMOUNT = 30
    LOG_ARCHIVES_MAX_TOTAL_SIZE = 3_221_225_472  # 3GB in bytes
    LOG_BASE_FILENAME_REGEX = r'(?<=)([a-z-_]+)(?=_\d)'
    LOG_FULL_FILE_NAME_REGEX = r'(?<=)({base_name})(?=_\d)'
