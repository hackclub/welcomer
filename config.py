import os
from dotenv import load_dotenv
from messages import WELCOME_MESSAGE

load_dotenv()


class Config:
    SLACK_BOT_TOKEN: str = os.environ.get("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET: str = os.environ.get("SLACK_SIGNING_SECRET", "")
    SLACK_APP_TOKEN: str = os.environ.get("SLACK_APP_TOKEN", "")

    BOT_ENABLED: bool = os.environ.get("BOT_ENABLED", "true").lower() == "true"
    BATCH_SIZE: int = int(os.environ.get("BATCH_SIZE", "1000"))

    CHANNEL_PREFIX: str = os.environ.get("CHANNEL_PREFIX", "welcome")

    WELCOME_MESSAGE: str = WELCOME_MESSAGE

    PIN_WELCOME_MESSAGE: bool = os.environ.get("PIN_WELCOME_MESSAGE", "true").lower() == "true"

    DEFAULT_CHANNELS: list[str] = [
        c.strip() for c in os.environ.get(
            "DEFAULT_CHANNELS",
            "C0EA9S0A0,C6C026NHJ,C01504DCLVD,C0266FRGT,C05B6DBN802,C01AS1YEM8A,C078Q8PBD4G,C0266FRGV"
        ).split(",") if c.strip()
    ]

    OPTIN_CHANNELS: dict[str, str] = {
        "C0710J7F4U9": "Would you like to join this channel?",
    }

    OPTIN_PROMPT_CHANNEL: str = os.environ.get("OPTIN_PROMPT_CHANNEL", "C0EA9S0A0")
    WELCOME_COMMITTEE_CHANNEL: str = os.environ.get("WELCOME_COMMITTEE_CHANNEL", "")

    REDIS_URL: str = os.environ.get("REDIS_URL", "")
    LOG_CHANNEL: str = os.environ.get("LOG_CHANNEL", "")

    # Users and groups to add to every new welcome channel (comma-separated IDs)
    WELCOME_CHANNEL_MEMBERS: list[str] = [
        m.strip() for m in os.environ.get("WELCOME_CHANNEL_MEMBERS", "").split(",") if m.strip()
    ]
    WELCOME_CHANNEL_GROUPS: list[str] = [
        g.strip() for g in os.environ.get("WELCOME_CHANNEL_GROUPS", "").split(",") if g.strip()
    ]

    @classmethod
    def get_channel_name(cls, number: int) -> str:
        if number == 1:
            return cls.CHANNEL_PREFIX
        return f"{cls.CHANNEL_PREFIX}-{number - 1}"

    @classmethod
    def is_welcome_channel_name(cls, name: str) -> bool:
        if name == cls.CHANNEL_PREFIX:
            return True
        return name.startswith(f"{cls.CHANNEL_PREFIX}-")

    @classmethod
    def validate(cls) -> list[str]:
        errors = []
        if not cls.SLACK_BOT_TOKEN:
            errors.append("SLACK_BOT_TOKEN is required")
        if not cls.SLACK_SIGNING_SECRET:
            errors.append("SLACK_SIGNING_SECRET is required")
        if cls.BATCH_SIZE < 1:
            errors.append("BATCH_SIZE must be at least 1")
        return errors
