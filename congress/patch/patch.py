from typing import Any
import os
import govinfo
import bills
import boto3
from botocore.errorfactory import ClientError
import smart_open

session = boto3.Session(profile_name='Democrasee')
client = session.client('s3')
transport_params = {'client': client}
bucket = 'democrasee-storage'

original_open = open
original_exists = os.path.exists

def open_wrapper(uri: Any, mode: str = 'r', *args):
    if isinstance(uri, str) and uri.startswith('raw'):
        s3_url = f"s3://{bucket}/{uri}"
        file = smart_open.open(uri=s3_url, mode=mode,
                               transport_params=transport_params)
        return file

    return original_open(uri, mode, *args)


def exists(path: Any):
    try:
        if (isinstance(path, str) and path.startswith('raw')):
            client.get_object(
                Bucket=bucket,
                Key=path
            )

            return True

        return original_exists(path)
    except ClientError as e:
        return False


def cache_dir_wrapper():
    return 'raw/congress/cache'


def data_dir_wrapper():
    return 'raw/congress/data'

def mkdir_p(path):
    return None

def patch(task_name):
    govinfo.utils.mkdir_p = mkdir_p
    govinfo.utils.cache_dir = cache_dir_wrapper
    govinfo.utils.data_dir = data_dir_wrapper
    govinfo.os.path.exists = exists

    bills.utils.mkdir_p = mkdir_p
    bills.utils.cache_dir = cache_dir_wrapper
    bills.utils.data_dir = data_dir_wrapper
    bills.os.path.exists = exists
    
    __builtins__['open'] = open_wrapper
