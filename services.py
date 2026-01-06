import os
from dotenv import load_dotenv


load_dotenv()  # Load environment variables from .env file


def configure_logfire():
    import logfire
    logfire.configure(token=_get_logfire_token())

def _get_logfire_token():
    return os.getenv("LOGFIRE_TOKEN")