import logging
import sys

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import Config
from state import InMemoryState, RedisState
from channel_manager import ChannelManager
from slack_logger import SlackLogHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    config_errors = Config.validate()
    if config_errors:
        for error in config_errors:
            logger.error(f"Config error: {error}")
        sys.exit(1)

    app = App(
        token=Config.SLACK_BOT_TOKEN,
        signing_secret=Config.SLACK_SIGNING_SECRET,
    )

    if Config.REDIS_URL:
        state_backend = RedisState(Config.REDIS_URL)
        logger.info("Using Redis for state")
    else:
        state_backend = InMemoryState()
        logger.info("Using in-memory state (set REDIS_URL for persistence)")

    channel_manager = ChannelManager(app.client, state_backend)

    if Config.LOG_CHANNEL:
        slack_handler = SlackLogHandler(app.client, Config.LOG_CHANNEL)
        logging.getLogger().addHandler(slack_handler)
        logger.info("Slack log channel enabled")

    @app.event("team_join")
    def handle_team_join(event: dict, logger: logging.Logger):
        if not Config.BOT_ENABLED:
            return

        user = event.get("user", {})
        user_id = user.get("id")

        if not user_id or user.get("is_bot"):
            return

        # If user is a guest, wait until they become full member
        if user.get("is_restricted") or user.get("is_ultra_restricted"):
            logger.info(f"New guest {user_id}, waiting for promotion")
            state_backend.add_pending_guest(user_id)
            return

        logger.info(f"Processing new full member: {user_id}")
        try:
            channel_manager.add_user_to_welcome_channel(user_id)
        except Exception:
            logger.exception("Error processing team_join")

    @app.event("member_joined_channel")
    def handle_member_joined(event: dict, client, logger: logging.Logger):
        logger.info(f"member_joined_channel event: {event}")
        
        if not Config.BOT_ENABLED:
            return

        user_id = event.get("user")
        channel_id = event.get("channel")

        if not user_id or not channel_id:
            return

        current_state = state_backend.get_state()
        is_welcome_channel = channel_id == current_state.current_channel_id
        logger.info(f"Channel {channel_id} vs current {current_state.current_channel_id}, is_welcome={is_welcome_channel}")

        if not is_welcome_channel:
            try:
                info = client.conversations_info(channel=channel_id)
                channel_name = info["channel"]["name"]
                is_welcome_channel = Config.is_welcome_channel_name(channel_name)
                logger.info(f"Channel name: {channel_name}, is_welcome_channel: {is_welcome_channel}")
            except Exception as e:
                logger.warning(f"Failed to get channel info: {e}")

        if not is_welcome_channel:
            return

        # Only process if user hasn't been handled by team_join
        if not state_backend.is_user_processed(user_id):
            try:
                channel_manager.add_user_to_welcome_channel(user_id)
            except Exception:
                logger.exception("Failed to process new user from channel join")

    @app.event("message")
    def handle_message_events(body, logger):
        pass

    @app.action("optin_join")
    def handle_optin_join(ack, body, client):
        ack()
        user_id = body["user"]["id"]
        channel_id = body["actions"][0]["value"]

        success = channel_manager._invite_user(channel_id, user_id)
        if success:
            client.chat_postEphemeral(
                channel=body["channel"]["id"],
                user=user_id,
                text=f"You've been added to <#{channel_id}>!",
            )
        else:
            client.chat_postEphemeral(
                channel=body["channel"]["id"],
                user=user_id,
                text=f"Couldn't add you to <#{channel_id}>. Try joining manually.",
            )

    @app.action("optin_decline")
    def handle_optin_decline(ack, body, client):
        ack()
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=body["user"]["id"],
            text="No problem! You can always join later.",
        )

    @app.command("/helpme")
    def handle_help_command(ack, body, client, logger):
        logger.info(f"Received /i-need-help command from {body['user_id']}")
        ack()
        user_id = body["user_id"]

        if not Config.WELCOME_COMMITTEE_CHANNEL:
            client.chat_postEphemeral(
                channel=body["channel_id"],
                user=user_id,
                text="Help requests aren't configured yet. Ask in a public channel!",
            )
            return

        client.chat_postEphemeral(
            channel=body["channel_id"],
            user=user_id,
            text="Need help?",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":wave: *Need help getting started?*\n\nClick below and someone from our welcome committee will reach out!"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Ask for Help"},
                            "style": "primary",
                            "action_id": "request_help",
                        },
                    ],
                },
            ],
        )

    @app.action("request_help")
    def handle_help_request(ack, body, client):
        ack()
        user_id = body["user"]["id"]

        if not Config.WELCOME_COMMITTEE_CHANNEL:
            return

        try:
            client.chat_postMessage(
                channel=Config.WELCOME_COMMITTEE_CHANNEL,
                text=f"<@{user_id}> needs help!",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":raising_hand: <@{user_id}> is looking for help!\n\nCan someone DM them?"
                        }
                    },
                ],
            )

            client.chat_postEphemeral(
                channel=body["channel"]["id"],
                user=user_id,
                text=":white_check_mark: Request sent! Someone will DM you soon.",
            )
            logger.info(f"Help request sent for user {user_id}")

        except Exception as e:
            logger.error(f"Failed to send help request: {e}")
            client.chat_postEphemeral(
                channel=body["channel"]["id"],
                user=user_id,
                text="Something went wrong. Try again or ask in a public channel.",
            )

    @app.event("user_change")
    def handle_user_change(event: dict, logger: logging.Logger):
        user = event.get("user", {})
        user_id = user.get("id")
        
        logger.info(f"user_change event: {user_id}, restricted={user.get('is_restricted')}, ultra={user.get('is_ultra_restricted')}")
        
        if not Config.BOT_ENABLED:
            return

        if not user_id:
            return

        is_restricted = user.get("is_restricted", False)
        is_ultra_restricted = user.get("is_ultra_restricted", False)

        if not is_restricted and not is_ultra_restricted:
            is_pending = state_backend.is_pending_guest(user_id)
            logger.info(f"User {user_id} is_pending_guest: {is_pending}")
            if is_pending:
                logger.info(f"Guest {user_id} promoted to full member")
                try:
                    channel_manager.process_promoted_guest(user_id)
                except Exception:
                    logger.exception("Failed to process promoted guest")

    logger.info("=" * 50)
    logger.info("Welcome Bot starting...")
    logger.info(f"Enabled: {Config.BOT_ENABLED}")
    logger.info(f"Batch size: {Config.BATCH_SIZE}")
    logger.info(f"Channel format: {Config.get_channel_name(1)}, {Config.get_channel_name(2)}, ...")
    logger.info("=" * 50)

    if Config.SLACK_APP_TOKEN:
        handler = SocketModeHandler(app, Config.SLACK_APP_TOKEN)
        handler.start()
    else:
        app.start(port=3000)


if __name__ == "__main__":
    main()
