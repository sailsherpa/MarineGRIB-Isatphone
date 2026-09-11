import requests
import random
import time

import sys

sys.path.append(".")
from transmitter import configs



######## HELPERS ########

def _split_message(gribmessage):
    """
    Splits a given grib message into chunks and encapsulates each chunk with its index.

    Args:
    gribmessage (str): The grib message that needs to be split into chunks.

    Returns:
    list: A list of formatted strings where each string has the format `msg {index}/{total_splits}:\n{chunk}\nend`.
    """
    total_splits = (len(gribmessage) + configs.MESSAGE_SPLIT_LENGTH - 1) // configs.MESSAGE_SPLIT_LENGTH

    chunks = [gribmessage[i:i + configs.MESSAGE_SPLIT_LENGTH] for i in range(0, len(gribmessage), configs.MESSAGE_SPLIT_LENGTH)]

    formatted_chunks = [
        f"msg {index + 1}/{total_splits}:\n{chunk}\nend"
        for index, chunk in enumerate(chunks)
    ]
    return formatted_chunks


