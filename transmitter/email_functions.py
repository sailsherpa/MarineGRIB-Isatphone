import os
import re
import pickle
import base64
import time
from email.mime.text import MIMEText
from base64 import urlsafe_b64decode
from datetime import datetime
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

import sys
sys.path.append(".")
from transmitter import configs
from transmitter import saildoc_functions as saildoc_func
from transmitter import inmarsat_functions as inmarsat_func


# Set up the Gmail API: https://developers.google.com/gmail/api/quickstart/python


def gmail_authenticate():
    """Authenticates the user and returns the Gmail API service."""
    creds = None
    if os.path.exists(configs.TOKEN_PATH):  # Check for existing token
        with open(configs.TOKEN_PATH, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        creds = _get_new_or_refreshed_credentials(creds)
        # Save the credentials for the next run
        with open(configs.TOKEN_PATH, "wb") as token:
            pickle.dump(creds, token)
    return build('gmail', 'v1', credentials=creds)


def process_new_inmarsat_request(auth_service):
    """
    Check for new messages, process them, and record their IDs.

    Args:
        auth_service (obj): The authentication service object.

    Returns:
        tuple or None: A tuple containing the path to the downloaded GRIB attachment and the Garmin reply URL
                       if successful, None otherwise.
    """
    previous_messages = _load_previous_messages()
    unanswered_messages = _get_new_message_ID(auth_service, previous_messages)

    if not unanswered_messages:
        return None

    grib_path = None
    inmarsat_reply_email = None

    for message_id in unanswered_messages:
        print("\r\nNew msg received with ID:", message_id, flush=True)
        try:
            grib_path, inmarsat_reply_email = _request_and_process_saildocs_grib(message_id, auth_service)
            print(f"Answered message {message_id}", flush=True)
        except Exception as e:
            print(f"Error answering message {message_id}: {e}", flush=True)
        finally:
            _append_to_previous_messages(message_id)

    return grib_path, inmarsat_reply_email






######## HELPERS ########


def _build_gmail_message(destination, obj, body):
    """Construct a MIMEText message for Gmail API.

    Args:
    destination (str): Email address of the recipient.
    obj (str): Subject of the email.
    body (str): Body content of the email.

    Returns:
    dict: Gmail API compatible message structure.
    """
    message = MIMEText(body)
    message['to'] = destination
    message['from'] = configs.GMAIL_ADDRESS
    message['subject'] = obj

    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}



def _send_gmail_message(service, destination, obj, body):
    """Send an email message through Gmail API.

    Args:
    service: Authenticated Gmail API service instance.
    destination (str): Email address of the recipient.
    obj (str): Subject of the email.
    body (str): Body content of the email.

    Returns:
    dict: Information about the sent message.
    """
    return service.users().messages().send(
        userId="me",
        body=_build_gmail_message(destination, obj, body)
    ).execute()



def _search_gmail_messages(service, query):
    """Search for Gmail messages that match a query. Loop will continue retrieving pages of messages as long as there's a nextPageToken.

    Args:
    service: Authenticated Gmail API service instance.
    query (str): Query string to filter messages.

    Returns:
    list: List of matching message IDs.
    """
    page_token = None
    messages = []

    while True:
        # This method accepts the q query parameter, which supports most of the same advanced search syntax as the Gmail web interface
        result = service.users().messages().list(userId='me', q=query, pageToken=page_token).execute()
        if 'messages' in result:
            messages.extend(result['messages'])

        page_token = result.get('nextPageToken', None)
        if not page_token:
            break
    return messages



def _get_grib_attachment(service, msg_id, user_id='me'):
    """Retrieve and save the first GRIB attachment from a Gmail message.

    Args:
    service: Authenticated Gmail API service instance.
    msg_id (str): ID of the Gmail message.
    user_id (str, optional): Gmail user ID.

    Returns:
    str: Path to the downloaded GRIB attachment, or None if no suitable attachment found.
    """
    try:
        message = service.users().messages().get(userId=user_id, id=msg_id).execute()
        parts = message['payload']['parts']

        for part in parts:
            filename = part.get('filename')
            if filename and filename.endswith('.grb') and 'attachmentId' in part['body']:
                path = _download_gmail_attachment(service, user_id, msg_id, part['body']['attachmentId'], filename)
                return path

        print("No GRIB attachment found.")
        return None

    except Exception as error:
        print(f'An error occurred: {error}')
        return None



def _request_and_process_saildocs_grib(message_id, auth_service):
    """
    Request Saildocs GRIB data, process the response, and return the GRIB path along with the Garmin reply URL.

    Args:
        message_id (str): The ID of the InReach message to process.
        auth_service (obj): The authentication service object.

    Returns:
        tuple or False: A tuple containing the path to the downloaded GRIB attachment and the Garmin reply URL
                       if successful, False otherwise.
    """

    msg_text, inmarsat_reply_email = _fetch_message_text_and_url(message_id, auth_service)

    # Make sure the reply email is from an Inmarsat phone address
    if not re.search(configs.ALLOWED_REPLY_EMAIL_REGEXP, inmarsat_reply_email):
        print('Error - Message received from non-Inmarsat address: ', inmarsat_reply_email)
        return False

    # Make sure the request is a vaild salldocs request
    if not re.search(r'^send\s+.*', msg_text):
        print('Error - Invalid Saildocs request: ', msg_text)
        return False
    
    # request saildocs grib data
    # _send_gmail_message(auth_service, configs.SAILDOCS_EMAIL_QUERY, "", "send " + msg_text)
    _send_gmail_message(auth_service, configs.SAILDOCS_EMAIL_QUERY, "", msg_text)
    time_sent = datetime.utcnow()
    last_response = saildoc_func.wait_for_saildocs_response(auth_service, time_sent)

    if not last_response:
        print('Error - Saildocs timeout for message: ', message_id)
        return False

    # process the saildocs response
    try:
        grib_path = _get_grib_attachment(auth_service, last_response['id'])
    except:
        print('Error - Could not download grib attachment for message: ', message_id)
        return False


    return grib_path, inmarsat_reply_email


def _get_new_or_refreshed_credentials(creds):
    """Helper to obtain new credentials or refresh expired ones.

    Args:
    creds: google.oauth2.credentials.Credentials object

    Returns:
    google.oauth2.credentials.Credentials: Refreshed or newly obtained credentials
    """
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(configs.CREDENTIALS_PATH, configs.SCOPES)
        creds = flow.run_local_server(port=0)
    return creds


def _download_gmail_attachment(service, user_id, msg_id, att_id, filename):
    """Helper to download and save an attachment from a Gmail message.

    Args:
    service: Authenticated Gmail API service instance.
    user_id (str): Gmail user ID. Use 'me' for the authenticated user.
    msg_id (str): ID of the Gmail message.
    att_id (str): ID of the attachment to download.
    filename (str): Filename to save the attachment.

    Returns:
    str: Path to the downloaded attachment.
    """
    att = service.users().messages().attachments().get(userId=user_id, messageId=msg_id, id=att_id).execute()
    data = att['data']
    file_data = base64.urlsafe_b64decode(data.encode('UTF-8'))

    path = os.path.join(configs.FILE_PATH, filename)
    with open(path, 'wb') as f:
        f.write(file_data)

    return path


def _load_previous_messages():
    """
    Helper to load previously processed messages from the file.

    Returns:
        set: A set of message IDs that have been processed before.
    """
    with open(configs.LIST_OF_PREVIOUS_MESSAGES_FILE_LOCATION, 'r') as f:
        return set(f.read().splitlines())


def _append_to_previous_messages(message_id):
    """
    Helper to append a new message ID to the file.

    Args:
        message_id (str): The ID of the message to be appended.
    """
    with open(configs.LIST_OF_PREVIOUS_MESSAGES_FILE_LOCATION, 'a') as f:
        f.write(f'{message_id}\n')


def _get_new_message_ID(auth_service, previous_messages):
    """
    Helper to retrieve new Inmarsat messages that haven't been processed.

    Args:
        auth_service (obj): The authentication service object.
        previous_messages (set): A set of message IDs that have been processed before.

    Returns:
        set: A set of new message IDs that haven't been processed.
    """
    # inmarsat_msgs = _search_gmail_messages(auth_service, configs.SERVICE_EMAIL)
    inmarsat_msgs = _search_gmail_messages(auth_service, configs.ALLOWED_EMAIL_QUERY  )    # Only allow messages from Inmarsat phones to be processed
    # configs.SERVICE_EMAIL)
    inmarsat_msgs_ids = {msg['id'] for msg in inmarsat_msgs}

    return inmarsat_msgs_ids.difference(previous_messages)


def _fetch_message_text_and_url(message_id, auth_service):
    """
    Retrieve the content of a message and extract the text and reply URL.

    Args:
        message_id (str): The ID of the message to retrieve.
        auth_service (obj): The authentication service object.

    Returns:
        tuple: The extracted message text and Garmin reply URL.
    """
    msg = auth_service.users().messages().get(userId='me', id=message_id).execute()
    msg_text = urlsafe_b64decode(msg['payload']['body']['data']).decode().split('\r')[0].lower()
    msg_headers = msg['payload']['headers']
    reply_email_address = next(
        (header['value'] for header in msg_headers
#         if header['name'].lower() == 'from' and re.search(r'@message\.inmarsat\.com$', header['value'])),          #  Use regex to match the Inmarsat email address
         if header['name'].lower() == 'from' ),
        None,
    )


    return msg_text, reply_email_address


def send_grib_emails_to_inmarsat(auth_service, emailaddr, gribmessage):
    """
    Splits the gribmessage and sends each part to inmarsat.

    Parameters:
    - emailaddr (str): The target emailaddr for the inmarsat phone (e.g. "870776725746@message.inmarsat.com" ).
    - gribmessage (str): The full message string to be split and sent.

    Returns:
    - list: A list of response objects from the inmarsat API for each sent message.
    """
    message_parts = inmarsat_func._split_message(gribmessage)
    responses = [_send_email_to_inmarsat(auth_service, emailaddr, part) for part in message_parts]


    # Introducing a delay to prevent overwhelming the API
    time.sleep(configs.DELAY_BETWEEN_MESSAGES)

    return responses

def _send_email_to_inmarsat(auth_service, emailaddr, message_str):
    """
    Sends an email message to the specified inmarsat emailaddr.

    Args:
    emailaddr (str): The inmarsat endpoint emailaddr to send the post request.
    message_str (str): The message string to be sent to inmarsat.

    Returns:
    Response: A Response object containing the server's response to the request.
    """
    response =_send_gmail_message(auth_service, emailaddr, "", message_str)

    print('Reply to inmarsat Sent: ', message_str)

#  if response.status_code == 200:
#         print('Reply to inmarsat Sent:', message_str)
#     else:
#         print('Error sending part:', message_str)
#         print(f'Status Code: {response.status_code}')
#         print(f'Response Content: {response.content}')

    return response