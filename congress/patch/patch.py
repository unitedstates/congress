from typing import Any
import os
import boto3
from botocore.errorfactory import ClientError
import smart_open
import logging
from functools import wraps

# The patch module is loaded after the task module is loaded, so all task
# modules are on the import path.
from congress.tasks import utils

session = boto3.Session(profile_name="Democrasee")
client = session.client("s3")
transport_params = {"client": client}
bucket = "democrasee-storage"

__all__ = [
    "patch",
    "open_wrapper",
    "exists_wrapper",
    "cache_dir_wrapper",
    "data_dir_wrapper",
    "mkdir_p_wrapper",
]


def open_wrapper(original_open):
    @wraps(original_open)
    def _open(uri: Any, mode: str = "r", *args):
        uri_as_string = str(uri)

        if uri_as_string.startswith("raw"):
            s3_url = f"s3://{bucket}/{uri_as_string}"
            file = smart_open.open(
                uri=s3_url, mode=mode, transport_params=transport_params
            )
            logging.info(f"Fetching from S3 -> {s3_url}")

            return file

        return original_open(uri, mode, *args)

    return _open


def exists_wrapper(original_exists):
    @wraps(original_exists)
    def _exists(path):
        try:
            uri_as_string = str(path)

            if uri_as_string.startswith("raw"):
                client.get_object(Bucket=bucket, Key=uri_as_string)

                return True

            return original_exists(path)
        except ClientError as e:
            return False

    return _exists


def cache_dir_wrapper():
    return "raw/congress/cache"


def data_dir_wrapper():
    return "raw/congress/data"


def mkdir_p_wrapper(original_mkdir_p):
    @wraps(original_mkdir_p)
    def _mkdir_p(path):
        return None

    return _mkdir_p


def patch(task_name):
    utils.data_dir = data_dir_wrapper
    utils.cache_dir = cache_dir_wrapper
    utils.mkdir_p = mkdir_p_wrapper(utils.mkdir_p)

    os.path.exists = exists_wrapper(os.path.exists)
    __builtins__["open"] = open_wrapper(open)
