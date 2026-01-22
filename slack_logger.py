import logging
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


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
