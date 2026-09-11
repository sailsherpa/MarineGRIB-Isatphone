import time
import base64
import zlib
from email.utils import parsedate_to_datetime
import sys
sys.path.append(".")
from transmitter import configs
from transmitter import email_functions as email_func


def encode_saildocs_grib_file(file_path):
    """
    Reads the content of a GRIB file, compresses it using zlib, then encodes the compressed data into a base64 string.

    Args:
    file_path (str): Path to the GRIB file that needs to be encoded.

    Returns:
    str: Base64 encoded string representation of the zlib compressed GRIB file content.
    """

    # Open the file in binary read mode and read its content
    with open(file_path, 'rb') as file:
        grib_binary = file.read()

    # Compress the binary content using zlib
    compressed_grib = zlib.compress(grib_binary)

    # Convert the compressed content to a base64 encoded string
    encoded_data = base64.b64encode(compressed_grib).decode('utf-8')

    return encoded_data



def wait_for_saildocs_response(auth_service, time_sent):
    """Wait for a SailDocs response and verify if the response matches the request timestamp.

    Args:
    auth_service: Authenticated Gmail API service instance.
    time_sent (datetime): Timestamp of the SailDocs request.

    Returns:
    dict or None: Returns the latest email response or None if no valid response is received within the timeout.
    """
    for _ in range(60): # loop for a maximum of 60 iterations (10 seconds sleep each)
        time.sleep(10) # sleep for 10 seconds before checking for new emails
        last_response = email_func._search_gmail_messages(auth_service, configs.SAILDOCS_RESPONSE_EMAIL)[0]
        received_header = auth_service.users().messages().get(userId='me', id=last_response['id']).execute()['payload']['headers'][-1]['value']
        stripped_date = received_header.split('(UTC)')[0].strip()        
        try:
            # An error might occur if the string contains millisecond decimals (.0569), which strictly violates the RFC 2822 / RFC 5322 email date standard.
            # Split at the dot and take everything before it
            clean_date_str = stripped_date.split('.')[0]  # Result: "10 Sep 2026 20:08:49"

            time_received = parsedate_to_datetime(clean_date_str)

            if time_received > time_sent: # compare the received timestamp with the timestamp of the SailDocs request
                return last_response
            
        except ValueError:
            print(f'Error - Invalid date format in email: {stripped_date}')
            continue    

        
    return None
