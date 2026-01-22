from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol

import redis


@dataclass
class BotState:
    current_channel_number: int = 1
    current_channel_id: str | None = None
    current_count: int = 0
    processed_users: set[str] = field(default_factory=set)
    pending_guests: set[str] = field(default_factory=set)


class StateBackend(Protocol):
    def get_state(self) -> BotState: ...
    def save_state(self, state: BotState) -> None: ...
    def mark_user_processed(self, user_id: str) -> None: ...
    def unmark_user_processed(self, user_id: str) -> None: ...
    def is_user_processed(self, user_id: str) -> bool: ...
    def add_pending_guest(self, user_id: str) -> None: ...
    def remove_pending_guest(self, user_id: str) -> None: ...
    def is_pending_guest(self, user_id: str) -> bool: ...


class RedisState:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.state_key = "welcome_bot:state"
        self.processed_key = "welcome_bot:processed"
        self.pending_key = "welcome_bot:pending_guests"

    def get_state(self) -> BotState:
        data = self.redis.hgetall(self.state_key)
        return BotState(
            current_channel_number=int(data.get("channel_number", 1)),
            current_channel_id=data.get("channel_id") or None,
            current_count=int(data.get("count", 0)),
        )

    def save_state(self, state: BotState) -> None:
        self.redis.hset(self.state_key, mapping={
            "channel_number": state.current_channel_number,
            "channel_id": state.current_channel_id or "",
            "count": state.current_count,
        })

    def mark_user_processed(self, user_id: str) -> None:
        self.redis.sadd(self.processed_key, user_id)

    def unmark_user_processed(self, user_id: str) -> None:
        self.redis.srem(self.processed_key, user_id)

    def is_user_processed(self, user_id: str) -> bool:
        return self.redis.sismember(self.processed_key, user_id)

    def add_pending_guest(self, user_id: str) -> None:
        self.redis.sadd(self.pending_key, user_id)

    def remove_pending_guest(self, user_id: str) -> None:
        self.redis.srem(self.pending_key, user_id)

    def is_pending_guest(self, user_id: str) -> bool:
        return self.redis.sismember(self.pending_key, user_id)


class InMemoryState:
    def __init__(self):
        self._state = BotState()
        self._lock = Lock()

    def get_state(self) -> BotState:
        with self._lock:
            return self._state

    def save_state(self, state: BotState) -> None:
        with self._lock:
            self._state = state

    def mark_user_processed(self, user_id: str) -> None:
        with self._lock:
            self._state.processed_users.add(user_id)

    def unmark_user_processed(self, user_id: str) -> None:
        with self._lock:
            self._state.processed_users.discard(user_id)

    def is_user_processed(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._state.processed_users

    def add_pending_guest(self, user_id: str) -> None:
        with self._lock:
            self._state.pending_guests.add(user_id)

    def remove_pending_guest(self, user_id: str) -> None:
        with self._lock:
            self._state.pending_guests.discard(user_id)

    def is_pending_guest(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._state.pending_guests
