from typing import Any
import os
import boto3
from botocore.errorfactory import ClientError
import smart_open
import logging
from functools import wraps

# The patch module is loaded after the task module is loaded, so all task
# modules are on the import path.
from congress.tasks import utils, govinfo, bills, votes

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

            # logging.warn(f"opening: {s3_url}")

            file = smart_open.open(
                uri=s3_url, mode=mode, transport_params=transport_params
            )

            return file

        return original_open(uri, mode, *args)

    return _open

def etree_parse_wrapper(original_etree_parse):
    @wraps(original_etree_parse)
    def _etree_parse(source: Any, *args):
        _open = open_wrapper(open)
        
        uri_as_string = str(source)

        if uri_as_string.startswith("raw"):
            # logging.warn(f"opening xml file: {uri_as_string}")

            file = _open(uri_as_string)

            return original_etree_parse(file)

        return original_etree_parse(source, *args)

    return _etree_parse

def listdir_wrapper(original_listdir):
    @wraps(original_listdir)
    def _listdir(path):
        try:
            uri_as_string = str(path)
            directory, extension = os.path.splitext(path)

            if uri_as_string.startswith("raw"):
                if extension == "":
                    prefix = f"{uri_as_string.rstrip('/')}/"
                    paginator = client.get_paginator("list_objects_v2")
                    pages = paginator.paginate(
                        Bucket=bucket,
                        Prefix=prefix,
                        Delimiter="/",
                    )

                    dirs = []

                    # logging.warn(f"listing dirs: {prefix}")

                    for page in pages:
                        page_dirs = list(
                            map(
                                lambda n: n.get("Prefix")
                                .replace(prefix, "")
                                .rstrip("/"),
                                page.get("CommonPrefixes", []),
                            )
                        )

                        dirs.extend(page_dirs)

                    return dirs

            return original_listdir(path)
        except ClientError as e:
            logging.warn(e)
            logging.warn(str(path))
            return False

    return _listdir


def exists_wrapper(original_exists):
    @wraps(original_exists)
    def _exists(path):
        try:
            uri_as_string = str(path)

            directory, extension = os.path.splitext(path)

            if uri_as_string.startswith("raw"):
                if extension == "":
                    # logging.warn(f"exists: {uri_as_string}")
                    return True

                try:
                    client.get_object(Bucket=bucket, Key=uri_as_string)
                    
                    return True
                except Exception as e:
                    # logging.warn(f"file does not exist: {uri_as_string}")
                    return False

            return original_exists(path)
        except ClientError as e:
            logging.warn(e)
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
    try:
        logging.warn(f"Patching task {task_name}")

        utils.data_dir = data_dir_wrapper
        utils.cache_dir = cache_dir_wrapper
        utils.mkdir_p = mkdir_p_wrapper(utils.mkdir_p)
        utils.zipfile.io.open =  open_wrapper(open)
        
        govinfo.utils.data_dir = utils.data_dir
        govinfo.utils.cache_dir = utils.cache_dir
        govinfo.utils.mkdir_p = utils.mkdir_p
        govinfo.os.path.exists = exists_wrapper(os.path.exists)
        govinfo.os.listdir = listdir_wrapper(os.listdir)
        govinfo.zipfile.io.open =  open_wrapper(open)
        govinfo.etree.parse = etree_parse_wrapper(govinfo.etree.parse)
        
        bills.utils.data_dir = utils.data_dir
        bills.utils.cache_dir = utils.cache_dir
        bills.utils.mkdir_p = utils.mkdir_p
        bills.os.path.exists = exists_wrapper(os.path.exists)
        bills.os.listdir = listdir_wrapper(os.listdir)

        votes.utils.data_dir = utils.data_dir
        votes.utils.cache_dir = utils.cache_dir
        votes.utils.mkdir_p = utils.mkdir_p
        votes.os.path.exists = exists_wrapper(os.path.exists)
        votes.os.listdir = listdir_wrapper(os.listdir)

        __builtins__["open"] = open_wrapper(open)
        
        logging.warn(f"Patched task {task_name}")
    except Exception as e:
        print(e)
