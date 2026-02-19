from os import getenv

from dotenv import load_dotenv


def get_env_var(env_key: str) -> str | None:
    """
    Get an environment variable. If not present, load .env file and try again.
    If failed again rise EnvironmentError.
    :param env_key:
    :return:
    """

    value = getenv(env_key)
    if value:
        return value.strip()
    else:
        load_dotenv()
        value = getenv(env_key)
        if not value:
            EnvironmentError(f"Environment variable `{env_key}` is not set")

    return value
