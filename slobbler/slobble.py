import logging
import typing as typ
from calendar import timegm
from dataclasses import dataclass
from datetime import datetime, timedelta
from json import dumps
from math import ceil
from random import choice, seed

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from slobbler.listener import TrackInfo


def remove_non_ascii(string: str) -> str:
    return string.encode("ascii", errors="ignore").decode()


def non_ascii_equals(left: str, right: str) -> bool:
    return remove_non_ascii(left) == remove_non_ascii(right)


class SlackStatus(typ.NamedTuple):
    text: str
    emoji: str


class Match(typ.TypedDict):
    field: str
    partial: str


class FilterMatch(Match):
    pass


class ExceptionMatch(Match):
    emoji: str
    message_format: str


@dataclass
class TrackFilter:
    passed: bool
    missing_fields: set[str]
    filter_match: FilterMatch
    exception_match: ExceptionMatch

    def __init__(
        self,
        required_fields: set[str],
        filters: typ.Iterable[FilterMatch],
        exceptions: typ.Iterable[ExceptionMatch],
        track_info: TrackInfo,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.passed = True
        self.missing_fields = set()
        self.filter_match = {}

        self.exception_match = next(
            (
                exception
                for exception in exceptions
                if exception["partial"] in track_info[exception["field"]]
            ),
            {},
        )
        if self.exception_match:
            # if an exception matches, skip all other possible filters
            self.logger.info(
                f'Exception: {self.exception_match["field"]} contains `{self.exception_match["partial"]}`'
            )
        else:
            # check for missing fields
            self.missing_fields = required_fields.intersection(
                track_info.empty_fields()
            )

            if self.missing_fields:
                self.passed = False
                self.logger.info(
                    f"Missing required fields: {', '.join(self.missing_fields)}"
                )
            else:
                # if no missing fields found, check filters
                self.filter_match = next(
                    (
                        filter
                        for filter in filters
                        if filter["partial"] in track_info[filter["field"]]
                    ),
                    {},
                )
                if self.filter_match:
                    self.passed = False
                    self.logger.info(
                        f'Filtered: {self.filter_match["field"]} contains `{self.filter_match["partial"]}`'
                    )


class SlackAPI:
    _slack_api_fmt = "https://slack.com/api/{command}"
    _max_status_size = 97

    def __init__(self, config: typ.Dict[str, typ.Any]):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.session = self.setup_session()
        self.session.headers.update(
            {"Authorization": f'Bearer {config["user_oauth_token"]}'}
        )
        self.session.params.update({"user": config["user_id"]})
        self.post_headers = {"Content-Type": "application/json; charset=utf-8"}

    @classmethod
    def trim_status_text(cls, status_text: str) -> str:
        return (
            (status_text[: cls._max_status_size] + "...")
            if len(status_text) > cls._max_status_size
            else status_text
        )

    def setup_session(self) -> Session:
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "OPTIONS", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session = Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        return session

    def read_profile(self) -> typ.Dict[str, typ.Any]:
        response = self.session.get(
            self._slack_api_fmt.format(command="users.profile.get")
        )
        assert response.ok, f"Bad response from server [{response}]: {response.text}"

        json_response = response.json()
        assert json_response["ok"], f"Failed because {json_response['error']}"
        return json_response["profile"]

    def write_profile(
        self, **profile: typ.Dict[str, typ.Any]
    ) -> typ.Dict[str, typ.Any]:
        response = self.session.post(
            self._slack_api_fmt.format(command="users.profile.set"),
            headers=self.post_headers,
            data=dumps({"profile": profile}).encode("utf-8"),
        )
        assert response.ok, f"Bad response from server [{response}]: {response.text}"

        json_response = response.json()
        assert json_response["ok"], f"Failed because {json_response['error']}"
        return json_response["profile"]


class Slobble:
    _minute_delta = timedelta(minutes=1)
    text_key = "status_text"
    emoji_key = "status_emoji"
    expiration_key = "status_expiration"
    profile_keys = {text_key, emoji_key}

    def __init__(self, slack_api: SlackAPI, config: typ.Dict[str, typ.Any]):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.slack_api = slack_api

        self.message_format: str = config.get("message_format", "{artist} - {title}")
        self.player_emoji: typ.Dict[str, str] = config.get("player_emoji", {})
        self.default_emojis: typ.Iterable[str] = tuple(
            config.get("default_emojis", ("",))
        )
        self.required_fields: set[str] = set(
            config.get("required_fields", {"artist", "title"})
        )
        self.filters: typ.Iterable[FilterMatch] = tuple(
            config.get("filters", tuple({}))
        )
        self.exceptions: typ.Iterable[ExceptionMatch] = tuple(
            config.get("exceptions", tuple({}))
        )
        self.set_expiration: bool = config.get("set_expiration", False)

        self.updatable_emojis = {
            "",  # empty emoji is updatable
            *self.default_emojis,
            *(emoji for emoji in self.player_emoji.values()),
            *(exception.get("emoji", "") for exception in self.exceptions),
        }

        seed()

    @classmethod
    def ceil_nearest_minute(cls, dt: datetime) -> datetime:
        return (
            datetime.min
            + ceil((dt - datetime.min) / cls._minute_delta) * cls._minute_delta
        )

    @classmethod
    def parse_status(cls, profile: typ.Dict[str, typ.Any]) -> SlackStatus:
        return SlackStatus(profile[cls.text_key], profile[cls.emoji_key])

    def handle_track_update(self, player_name: str, track_info: TrackInfo):
        current_status = self.can_update()
        if current_status:
            filter_result = TrackFilter(
                self.required_fields, self.filters, self.exceptions, track_info
            )
            if filter_result.passed:
                self.scrobble_status(
                    player_name,
                    current_status,
                    track_info,
                    filter_result.exception_match,
                )
            else:
                self.handle_stop_playing()

    def handle_stop_playing(self, player_name: str = None):
        if self.can_update():
            self.logger.info("Clearing status")
            self.write_status("", "", 0)

    def scrobble_status(
        self,
        player_name: str,
        current_status: SlackStatus,
        track_info: TrackInfo,
        exception: ExceptionMatch,
    ):
        status_text = self.slack_api.trim_status_text(
            # see if there is a custom message format in exception
            exception.get("message_format", self.message_format).format(
                **track_info.to_dict()
            )
        )
        if not non_ascii_equals(status_text, current_status.text):
            status_emoji = exception.get(
                "emoji",  # see if there is a custom emoji in exception
                self.pick_emoji(player_name),
            )
            expiration_time, expiration_epoch = self.calculate_expiration(
                track_info.length
            )
            self.logger.info(
                f"Setting status: {status_emoji}, {status_text}, {expiration_time}"
            )
            self.write_status(status_text, status_emoji, expiration_epoch)
        else:
            self.logger.warning("Skipping status update, nothing to change")

    def calculate_expiration(self, length_seconds: int) -> tuple[datetime | None, int]:
        if self.set_expiration and length_seconds:
            # sometimes slack the message expires too soon, round up to the nearest minute
            expiration_time = self.ceil_nearest_minute(
                datetime.utcnow() + timedelta(seconds=length_seconds)
            )
            return expiration_time, timegm(expiration_time.timetuple())
        return None, 0

    def can_update(self) -> SlackStatus | typ.Literal[False]:
        """don't override any other status, based upon the current emoji"""
        current_status = self.read_status()

        if current_status.emoji in self.updatable_emojis:
            return current_status

        self.logger.info(f"Cannot update because emoji is set: {current_status.emoji}")
        return False

    def pick_emoji(self, player_name: str) -> str:
        return self.player_emoji.get(
            player_name,  # try player name specific emoji
            choice(
                self.default_emojis
            ),  # fallback to a random choice of fallback emojis
        )

    def read_status(self) -> SlackStatus:
        return self.parse_status(self.slack_api.read_profile())

    def write_status(self, message: str, emoji: str, expiration: int) -> SlackStatus:
        response = self.slack_api.write_profile(
            **{
                self.text_key: message,
                self.emoji_key: emoji,
                self.expiration_key: expiration,
            }
        )

        return self.parse_status(response)


class NoScrobble:
    def __init__(self, *args, **kwargs):
        self.logger = logging.getLogger(self.__class__.__name__)

    def handle_track_update(self, player_name: str, track_info: TrackInfo):
        self.logger.info(f"handle_track_update({player_name=}, {track_info=})")

    def handle_stop_playing(self, player_name: str):
        self.logger.info(f"handle_stop_playing({player_name=})")
