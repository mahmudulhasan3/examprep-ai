import os
def get_env_variable(name: str):
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is not set in .env file")
    return value
