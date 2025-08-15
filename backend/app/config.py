from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database configuration
    DATABASE_URL: str = "sqlite:///./app.db"
    
    # OpenAI configuration
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"
    
    # Google Calendar configuration
    GOOGLE_CALENDAR_ID: str = ""
    GOOGLE_CREDENTIALS_PATH: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""
    
    # Email configuration
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = ""
    
    # Slack configuration
    SLACK_BOT_TOKEN: str = ""
    SLACK_CHANNEL_ID: str = ""
    
    class Config:
        env_file = ".env"


def get_settings() -> Settings:
    return Settings() 