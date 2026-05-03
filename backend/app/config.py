from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://stockuser:stockpass@localhost:5432/stockdb"
    secret_key: str = "change-me-in-production"
    micros_api_url: str = ""
    micros_api_key: str = ""
    sage_api_url: str = ""
    sage_client_id: str = ""
    sage_client_secret: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
