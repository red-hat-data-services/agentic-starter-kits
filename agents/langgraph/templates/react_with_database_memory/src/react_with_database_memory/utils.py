from os import getenv
from urllib.parse import quote_plus


def get_database_uri() -> str:
    """
    Construct PostgresSQL database URI from environment variables.

    Expected env vars:
    - POSTGRES_HOST
    - POSTGRES_PORT
    - POSTGRES_DB
    - POSTGRES_USER
    - POSTGRES_PASSWORD
    """
    host = getenv("POSTGRES_HOST")
    user = getenv("POSTGRES_USER")
    password = getenv("POSTGRES_PASSWORD")
    database = getenv("POSTGRES_DB")
    port = getenv("POSTGRES_PORT")

    missing = [
        name
        for name, val in [
            ("POSTGRES_HOST", host),
            ("POSTGRES_USER", user),
            ("POSTGRES_PASSWORD", password),
            ("POSTGRES_DB", database),
            ("POSTGRES_PORT", port),
        ]
        if not val
    ]
    if missing:
        raise ValueError(
            f"Required environment variables not set: {', '.join(missing)}"
        )

    assert host and user and password and database and port

    safe_host = quote_plus(host)
    safe_user = quote_plus(user)
    safe_password = quote_plus(password)

    return f"postgresql://{safe_user}:{safe_password}@{safe_host}:{port}/{database}"
