import logging
import re
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

SKIP_PATTERNS = [
    r"Rate limited, waiting",
]

SKIP_REGEX = re.compile("|".join(SKIP_PATTERNS))


class SlackLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return not SKIP_REGEX.search(record.getMessage())


class SlackLogHandler(logging.Handler):
    def __init__(self, client: WebClient, channel_id: str, level: int = logging.INFO):
        super().__init__(level)
        self.client = client
        self.channel_id = channel_id
        self.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            emoji = self._get_emoji(record.levelno)
            self.client.chat_postMessage(
                channel=self.channel_id,
                text=f"{emoji} `{record.levelname}` {record.getMessage()}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{emoji} *{record.levelname}*\n```{message}```",
                        },
                    }
                ],
            )
        except SlackApiError:
            pass
        except Exception:
            self.handleError(record)

    def _get_emoji(self, level: int) -> str:
        if level >= logging.ERROR:
            return ":x:"
        if level >= logging.WARNING:
            return ":warning:"
        return ":information_source:"
