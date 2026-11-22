import os


def get_env_variable(name: str):
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is not set in .env file")
    return value


def get_optional_env_variable(name: str, default: str = "") -> str:
    """Read a setting that may be missing; return the default when it is not set."""
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def env_flag(name: str, default: bool) -> bool:
    """Read a true/false setting such as EMAIL_VERIFICATION=false."""
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")
