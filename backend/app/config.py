from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://stockuser:stockpass@localhost:5432/stockdb"
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480  # 8 hours

    # Claude API (invoice OCR)
    anthropic_api_key: str = ""

    # Micros POS
    micros_api_url: str = ""
    micros_api_key: str = ""

    # Ingest pipeline
    ingest_watch_dir: str = "/data/ingest/micros"

    # COS variance flagging — absolute variance value (currency) above which a
    # CosFlag row is raised for an item in a period
    cos_flag_threshold_value: float = 200.0

    # Sage
    sage_api_url: str = ""
    sage_client_id: str = ""
    sage_client_secret: str = ""

    # Email (SMTP) — compatible with Office 365 and Gmail
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""  # defaults to smtp_user if blank

    # WhatsApp via Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""  # E.164: +14155238886 (Twilio sandbox) or your approved number

    class Config:
        env_file = ".env"


settings = Settings()
