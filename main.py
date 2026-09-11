import time
import sys

sys.path.append(".")
from transmitter import email_functions as email_func
from transmitter import saildoc_functions as saildoc_func
from transmitter import inmarsat_functions as inmarsat_func

if __name__ == "__main__":
    # authenticate Gmail API
    auth_service = email_func.gmail_authenticate()

    # check for new InReach messages every minute
    while True:
        print('Checking...', flush=True)

        # check for new messages and retrieve GRIB path and Inmarsat reply email
        result = email_func.process_new_inmarsat_request(auth_service)

        # if a new message is received
        if result is not None:

            grib_path, inmarsat_reply_email = result

            # encode GRIB to binary
            if ( grib_path is not None and inmarsat_reply_email is not None):

                encoded_grib = saildoc_func.encode_saildocs_grib_file(grib_path)

                # send the encoded GRIB to Inmarsat
                email_func.send_grib_emails_to_inmarsat(auth_service, inmarsat_reply_email, encoded_grib)

        # wait for the next check in 60 seconds
        time.sleep(60)