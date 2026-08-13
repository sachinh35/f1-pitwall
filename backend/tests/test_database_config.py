"""Unit tests for config/database_config.py's connection-string/params builders."""
from config.database_config import DatabaseConfig


def test_connection_string_without_password() -> None:
    DatabaseConfig.DB_USER = "sachinh"
    DatabaseConfig.DB_HOST = "localhost"
    DatabaseConfig.DB_PORT = "5432"
    DatabaseConfig.DB_NAME = "f1-analytics"
    DatabaseConfig.DB_PASSWORD = None

    assert DatabaseConfig.get_connection_string() == "postgresql://sachinh@localhost:5432/f1-analytics"
    assert DatabaseConfig.get_async_connection_string() == "postgresql://sachinh@localhost:5432/f1-analytics"


def test_connection_string_with_password() -> None:
    DatabaseConfig.DB_USER = "sachinh"
    DatabaseConfig.DB_HOST = "localhost"
    DatabaseConfig.DB_PORT = "5432"
    DatabaseConfig.DB_NAME = "f1-analytics"
    DatabaseConfig.DB_PASSWORD = "secret"

    expected = "postgresql://sachinh:secret@localhost:5432/f1-analytics"
    assert DatabaseConfig.get_connection_string() == expected
    assert DatabaseConfig.get_async_connection_string() == expected

    DatabaseConfig.DB_PASSWORD = None  # reset for other tests relying on the class default


def test_async_connection_params_without_password() -> None:
    DatabaseConfig.DB_USER = "sachinh"
    DatabaseConfig.DB_HOST = "localhost"
    DatabaseConfig.DB_PORT = "5432"
    DatabaseConfig.DB_NAME = "f1-analytics"
    DatabaseConfig.DB_PASSWORD = None

    params = DatabaseConfig.get_async_connection_params()
    assert params == {"host": "localhost", "port": "5432", "database": "f1-analytics", "user": "sachinh"}


def test_async_connection_params_with_password() -> None:
    DatabaseConfig.DB_USER = "sachinh"
    DatabaseConfig.DB_HOST = "localhost"
    DatabaseConfig.DB_PORT = "5432"
    DatabaseConfig.DB_NAME = "f1-analytics"
    DatabaseConfig.DB_PASSWORD = "secret"

    params = DatabaseConfig.get_async_connection_params()
    assert params["password"] == "secret"

    DatabaseConfig.DB_PASSWORD = None  # reset for other tests relying on the class default
