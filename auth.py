import msal
from config import TENANT_ID, CLIENT_ID, THUMBPRINT, CERT_PATH

def get_token():
    with open(CERT_PATH, "r") as f:
        key = f.read()

    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential={
            "thumbprint": THUMBPRINT,
            "private_key": key,
        }
    )

    token = app.acquire_token_for_client(
        scopes=["https://graph.microsoft.com/.default"]
    )

    if "access_token" not in token:
        raise Exception(token)

    return token["access_token"]