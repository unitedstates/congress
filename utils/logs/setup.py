import gzip
import logging
import os
import re
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from congress.common.constants.congress import CongressConstants
from common.constants.billml import BillMLConstants


class CompressingTimedRotatingFileHandler(TimedRotatingFileHandler):
    """TimedRotatingFileHandler with gzip compression on rotate."""

    def rotation_filename(self, file_name: str) -> str:
        """
        Extend the log filename to use gzip-ending.
        :param file_name: The default filename of this handler
        """
        return file_name.replace(".log.", "_") + '.log' + ".gz"

    def rotate(self, source: str, dest: str) -> None:
        """
        Rotate the current log
        :param source: The source filename. This is normally the base
                       filename, e.g. 'test.log'
        :param dest:   The destination filename. This is normally
                       what the source is rotated to, e.g. 'test.log.1'.
        """
        archives_folder = Path(dest).parent.absolute().joinpath('archives')
        Path(archives_folder).mkdir(parents=True, exist_ok=True)
        archive_filename = Path(dest).name
        output_filepath = os.path.join(archives_folder, archive_filename)

        CompressingTimedRotatingFileHandler.clean_up_archives_folder(
            archives_folder, archive_filename
        )

        source = Path(source)
        with source.open('rb') as f_in, gzip.open(
            filename=output_filepath, mode='wb', compresslevel=9
        ) as f_out:
            f_out.writelines(f_in)
        source.unlink()

    @staticmethod
    def clean_up_archives_folder(archives_folder: Path, archive_filename: str) -> None:
        """Given path to a folder and .gz filename removes stale and old .gz files in cases:

        1.if total number of .gz files exceeds maximum allowed amount.
        2.if total size of .gz exceeds total maximum allowed files size.
        """
        archive_base_name = CompressingTimedRotatingFileHandler.get_file_base_name(
            archive_filename
        )
        if not archive_base_name:
            return
        all_files = CompressingTimedRotatingFileHandler.get_folder_files(
            archives_folder
        )
        if not all_files:
            return
        full_name_regex = CongressConstants.LOG_FULL_FILE_NAME_REGEX.value.format(base_name=archive_base_name)
        target_files = sorted(
            [
                file_path
                for file_path in all_files
                if re.findall(full_name_regex, file_path.name)
            ],
            key=os.path.getctime,
            reverse=True,
        )
        if CompressingTimedRotatingFileHandler.check_files_amount(target_files):
            CompressingTimedRotatingFileHandler.remove_extra_files_by_amount(
                target_files
            )
        if CompressingTimedRotatingFileHandler.check_files_size(target_files):
            CompressingTimedRotatingFileHandler.remove_last_file(target_files)

    @staticmethod
    def get_folder_files(folder_path: Path) -> list[Path]:
        """Return list of files with .gz extension."""
        return [file_path for file_path in Path(folder_path).glob('*.gz')]

    @staticmethod
    def get_file_base_name(filename: str) -> str:
        """Return file name if it matches regex in constants."""
        x = re.findall(CongressConstants.LOG_BASE_FILENAME_REGEX.value, filename)
        return x[0] if len(x) > 0 else ''

    @staticmethod
    def check_files_amount(files: list[Path]) -> bool:
        """Check if total quantity of files exceeds maximum allowed amount."""
        return len(files) > CongressConstants.LOG_ARCHIVES_MAX_AMOUNT.value

    @staticmethod
    def remove_extra_files_by_amount(files: list[Path]) -> None:
        """Delete all files that exceeds maximum allowed amount."""
        for file in files[CongressConstants.LOG_ARCHIVES_MAX_AMOUNT.value:]:
            try:
                file.unlink()
            except FileNotFoundError:
                print('File already removed.')

    @staticmethod
    def check_files_size(files: list[Path]) -> bool:
        """Check if total size of files in folder exceeds maximum allowed amount."""
        return (
            CompressingTimedRotatingFileHandler.get_files_size(files)
            > CongressConstants.LOG_ARCHIVES_MAX_TOTAL_SIZE.value
        )

    @staticmethod
    def get_files_size(files: list[Path]) -> int:
        """Get sum of file sizes in bytes."""
        TOTAL_FILES_SIZE = 0
        for file in files:
            try:
                TOTAL_FILES_SIZE += file.stat().st_size
            except FileNotFoundError:
                continue
        return TOTAL_FILES_SIZE

    @staticmethod
    def remove_last_file(files: list[Path]) -> None:
        """Delete last file in provided list of files."""
        try:
            files[-1].unlink()
        except FileNotFoundError:
            print('File already deleted.')


def create_log_filepath(log_output_folder: str, log_file_base_name: str) -> str:
    """Creates log filepath."""
    log_file_name = f'{log_file_base_name}.log'
    return os.path.join(log_output_folder, log_file_name)


def setup_file_handler(
    log_filepath: str,
    log_format: str,
    when: str = 'midnight',
    interval: int = 1,
    backupCount: int = 0,
):
    """Creates logging handler for storing logs in file."""
    file_handler = CompressingTimedRotatingFileHandler(
        filename=log_filepath,
        when=when,
        interval=interval,
        backupCount=backupCount,
    )
    file_formatter = logging.Formatter(log_format)
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    return file_handler


def setup_stdout_handler(log_format: str, log_level: str):
    """Creates logging handler for stdout."""
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_formatter = logging.Formatter(log_format)
    stdout_handler.setFormatter(stdout_formatter)
    stdout_handler.setLevel(log_level)
    return stdout_handler


def default_handlers(
    log_format: str = CongressConstants.LOG_FORMAT.value,
    log_level: str = 'DEBUG',
    log_output_folder: str = CongressConstants.LOG_OUTPUT_FOLDER.value,
    log_file_base_name: str = CongressConstants.LOG_FILE_BASE_NAME.value,
):
    """Creates stdout and file log handlers."""
    stdout_handler = setup_stdout_handler(log_format, log_level)

    log_filepath = create_log_filepath(log_output_folder, log_file_base_name)
    file_handler = setup_file_handler(
        log_filepath=log_filepath,
        log_format=log_format,
        when=CongressConstants.LOG_FILE_INTERVAL_TYPE.value,
        interval=CongressConstants.LOG_FILE_INTERVAL.value,
        backupCount=0,
    )
    return [stdout_handler, file_handler]


def setup_logging(name: str, handlers: list) -> logging.Logger:
    """Return Logger class to set up logging for the project."""
    log = logging.getLogger(name)
    log.setLevel(logging.DEBUG)

    if not log.handlers:
        for handler in handlers:
            log.addHandler(handler)

    log.propagate = False
    return log
