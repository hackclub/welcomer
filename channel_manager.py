import logging
import time
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from config import Config
from state import StateBackend, BotState

logger = logging.getLogger(__name__)


class ChannelManager:
    def __init__(self, client: WebClient, state_backend: StateBackend):
        self.client = client
        self.state = state_backend

    def add_user_to_default_channels(self, user_id: str) -> None:
        for channel_id in Config.DEFAULT_CHANNELS:
            result = self._invite_user(channel_id, user_id)
            if result and result != "guest":
                logger.info(f"Added user to default channel {channel_id}")

    def send_optin_prompts(self, user_id: str) -> None:
        for channel_id, message in Config.OPTIN_CHANNELS.items():
            try:
                self.client.chat_postEphemeral(
                    channel=Config.OPTIN_PROMPT_CHANNEL,
                    user=user_id,
                    text=message,
                    blocks=[
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": f"*{message}*\n\nJoin <#{channel_id}>?"}
                        },
                        {
                            "type": "actions",
                            "elements": [
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "Yes, join!"},
                                    "style": "primary",
                                    "action_id": "optin_join",
                                    "value": channel_id,
                                },
                                {
                                    "type": "button",
                                    "text": {"type": "plain_text", "text": "No thanks"},
                                    "action_id": "optin_decline",
                                    "value": channel_id,
                                },
                            ],
                        },
                    ],
                )
                logger.info(f"Sent opt-in prompt for channel {channel_id}")
            except SlackApiError as e:
                logger.error(f"Failed to send opt-in prompt: {e.response['error']}")

    def process_promoted_guest(self, user_id: str) -> bool:
        if not self.state.is_pending_guest(user_id):
            return False

        logger.info(f"Processing promoted guest {user_id}")
        self.state.remove_pending_guest(user_id)

        state = self.state.get_state()
        state.processed_users.discard(user_id)
        self.state.save_state(state)

        return self.add_user_to_welcome_channel(user_id)

    def add_user_to_welcome_channel(self, user_id: str) -> bool:
        if self.state.is_user_processed(user_id):
            logger.info("User already processed, skipping")
            return True

        self.add_user_to_default_channels(user_id)
        self.send_optin_prompts(user_id)

        current_state = self.state.get_state()

        if not current_state.current_channel_id:
            current_state = self._create_or_get_channel(current_state)
            if not current_state.current_channel_id:
                logger.error("Failed to create or find welcome channel")
                return False

        if current_state.current_count >= Config.BATCH_SIZE:
            logger.info(f"Rotating to new channel (batch full: {current_state.current_count}/{Config.BATCH_SIZE})")
            current_state = self._rotate_to_next_channel(current_state)
            if not current_state.current_channel_id:
                logger.error("Failed to create rotated welcome channel")
                return False

        result = self._invite_user(current_state.current_channel_id, user_id)

        if result == "guest":
            logger.info("Guest user will be added to welcome channel after promotion")
            return True

        if result:
            current_state.current_count += 1
            self.state.save_state(current_state)
            self.state.mark_user_processed(user_id)
            logger.info(f"Added user to channel {current_state.current_channel_number} ({current_state.current_count}/{Config.BATCH_SIZE})")
        else:
            logger.error(f"Failed to invite user to welcome channel {current_state.current_channel_number}")

        return bool(result)

    def _create_or_get_channel(self, state: BotState) -> BotState:
        channel_name = Config.get_channel_name(state.current_channel_number)

        try:
            response = self.client.conversations_create(name=channel_name, is_private=True)
            channel_id = response["channel"]["id"]
            state.current_channel_id = channel_id
            state.current_count = 0
            self.state.save_state(state)
            self._post_welcome_message(channel_id)
            logger.info(f"Created new channel: {channel_name}")

        except SlackApiError as e:
            error = e.response["error"]
            if error == "name_taken":
                state = self._find_existing_channel(state, channel_name)
                if not state.current_channel_id:
                    logger.error(f"Channel {channel_name} exists but couldn't be found")
            else:
                logger.error(f"Failed to create channel: {error}")

        return state

    def _find_existing_channel(self, state: BotState, channel_name: str) -> BotState:
        try:
            cursor = None
            while True:
                for attempt in range(3):
                    try:
                        response = self.client.conversations_list(
                            types="private_channel",
                            exclude_archived=False,
                            limit=200,
                            cursor=cursor,
                        )
                        break
                    except SlackApiError as e:
                        if e.response["error"] == "ratelimited":
                            retry_after = int(e.response.headers.get("Retry-After", 5))
                            logger.warning(f"Rate limited, waiting {retry_after}s")
                            time.sleep(retry_after)
                        else:
                            raise
                else:
                    logger.error("Failed to list channels after retries")
                    return state

                for channel in response["channels"]:
                    if channel["name"] == channel_name:
                        channel_id = channel["id"]

                        if channel.get("is_archived"):
                            logger.info(f"Channel {channel_name} is archived, unarchiving...")
                            try:
                                self.client.conversations_unarchive(channel=channel_id)
                            except SlackApiError as e:
                                logger.error(f"Failed to unarchive: {e.response['error']}")
                                return state

                        self._ensure_bot_in_channel(channel_id)
                        state.current_channel_id = channel_id

                        info = self.client.conversations_info(channel=channel_id, include_num_members=True)
                        state.current_count = max(0, info["channel"].get("num_members", 1) - 1)
                        self.state.save_state(state)
                        logger.info(f"Found existing channel {channel_name} with {state.current_count} members")
                        return state

                cursor = response.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break

        except SlackApiError as e:
            logger.error(f"Failed to find channel: {e.response['error']}")

        return state

    def _rotate_to_next_channel(self, state: BotState) -> BotState:
        state.current_channel_number += 1
        state.current_channel_id = None
        state.current_count = 0
        return self._create_or_get_channel(state)

    def _ensure_bot_in_channel(self, channel_id: str) -> bool:
        try:
            self.client.conversations_join(channel=channel_id)
            return True
        except SlackApiError as e:
            if e.response["error"] == "already_in_channel":
                return True
            logger.error(f"Bot failed to join channel {channel_id}: {e.response['error']}")
            return False

    def _invite_user(self, channel_id: str, user_id: str) -> bool | str:
        max_retries = 3

        if not self._ensure_bot_in_channel(channel_id):
            return False

        for attempt in range(max_retries):
            try:
                self.client.conversations_invite(channel=channel_id, users=user_id)
                return True

            except SlackApiError as e:
                error = e.response["error"]

                if error == "already_in_channel":
                    return True

                if error == "ratelimited":
                    retry_after = int(e.response.headers.get("Retry-After", 2 ** attempt))
                    logger.warning(f"Rate limited, waiting {retry_after}s")
                    time.sleep(retry_after)
                    continue

                if error in ("user_is_restricted", "user_is_ultra_restricted"):
                    guest_type = "MCG" if error == "user_is_restricted" else "SCG"
                    logger.info(f"Skipping {guest_type} user for channel {channel_id}")
                    self.state.add_pending_guest(user_id)
                    return "guest"

                if error in ("cant_invite_self", "user_not_found", "method_not_supported_for_channel_type"):
                    logger.info(f"Skipping user ({error})")
                    return True

                logger.error(f"Failed to invite user: {error}")
                return False

        logger.error("Failed to invite user after max retries")
        return False

    def _post_welcome_message(self, channel_id: str) -> None:
        try:
            response = self.client.chat_postMessage(
                channel=channel_id,
                text=Config.WELCOME_MESSAGE,
                unfurl_links=False,
            )

            if Config.PIN_WELCOME_MESSAGE and response.get("ts"):
                try:
                    self.client.pins_add(channel=channel_id, timestamp=response["ts"])
                except SlackApiError as e:
                    logger.warning(f"Failed to pin message: {e.response['error']}")

        except SlackApiError as e:
            logger.error(f"Failed to post welcome message: {e.response['error']}")
