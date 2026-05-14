import uuid


def generate_session_token():
    return str(uuid.uuid4())