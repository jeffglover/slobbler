import logging
from calendar import timegm
from datetime import datetime, timedelta
from json import dumps
from math import ceil
from random import choice, seed
from typing import NamedTuple

import requests


def remove_non_ascii(string):
    return string.encode("ascii", errors="ignore").decode()


def non_ascii_equals(left, right):
    return remove_non_ascii(left) == remove_non_ascii(right)


class SlackStatusResponse(NamedTuple):
    text: str
    emoji: str


class SlackStatus:
    _slack_api_fmt = "https://slack.com/api/{command}"
    _max_status_size = 97
    _minute_delta = timedelta(minutes=1)
    text_key = "status_text"
    emoji_key = "status_emoji"
    expiration_key = "status_expiration"
    profile_keys = {text_key, emoji_key}

    def __init__(self, config):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.__dict__.update(config)
        self.headers = {"Authorization": f"Bearer {self.token}"}
        seed()

    @classmethod
    def trim_status_text(cls, status_text):
        return (
            (status_text[: cls._max_status_size] + "...")
            if len(status_text) > cls._max_status_size
            else status_text
        )

    @classmethod
    def ceil_nearest_minute(cls, dt):
        return (
            datetime.min
            + ceil((dt - datetime.min) / cls._minute_delta) * cls._minute_delta
        )

    @classmethod
    def calculate_expiration(cls, length_seconds):
        if length_seconds:
            # sometimes slack message expires too soon, round up to the nearest minute
            expiration_time = cls.ceil_nearest_minute(
                datetime.utcnow() + timedelta(seconds=length_seconds)
            )
            return expiration_time, timegm(expiration_time.timetuple())
        return None, 0

    @classmethod
    def parse_status(cls, profile):
        return SlackStatusResponse(profile[cls.text_key], profile[cls.emoji_key])

    def can_update(self):
        """don't override any other status, based upon the current emoji"""
        current_status = self.read_status()

        if current_status.emoji in self.valid_playing_emojis:
            return current_status

        self.logger.info(f"Cannot update because emoji is set: {current_status.emoji}")
        return False

    def pick_emoji(self, player_name):
        return self.playing_emoji.get(
            player_name,  # try player name specific emoji
            choice(
                self.fallback_emojis
            ),  # fallback to a random choice of fallback emojis
        )

    def read_status(self):
        return self.parse_status(self.read_profile())

    def read_profile(self):
        params = {"user": self.user_id}
        response = requests.get(
            self._slack_api_fmt.format(command="users.profile.get"),
            headers=self.headers,
            params=params,
        )
        assert response.ok, f"Bad response from server [{response}]: {response.text}"

        json_response = response.json()
        assert json_response["ok"], f"Failed because {json_response['error']}"
        return json_response["profile"]

    def write_status(self, message, emoji, expiration):
        response = self.write_profile(
            **{
                self.text_key: message,
                self.emoji_key: emoji,
                self.expiration_key: expiration,
            }
        )

        if response:
            return self.parse_status(response)
        return response

    def write_profile(self, **profile):
        headers = {
            **self.headers,
            "Content-Type": "application/json; charset=utf-8",
        }
        params = {"user": self.user_id}
        status_payload = {"profile": profile}

        response = requests.post(
            self._slack_api_fmt.format(command="users.profile.set"),
            headers=headers,
            params=params,
            data=dumps(status_payload).encode("utf-8"),
        )
        # TODO: add retry handling
        if response.status_code == 429:
            self.logger.error(f"Error writing status, rate limited")
            return False

        assert response.ok, f"Bad response from server [{response}]: {response.text}"

        json_response = response.json()
        assert json_response["ok"], f"Failed because {json_response['error']}"
        return json_response["profile"]


class Slobble:
    _track_message_fmt = "{artist} - {title}"

    def __init__(self, config):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.slack = SlackStatus(config)

    def handle_track_update(self, player_name, track_info):
        current_status = self.slack.can_update()
        if current_status and track_info.artist and track_info.title:
            status_text = self.slack.trim_status_text(
                self._track_message_fmt.format(**track_info.to_dict())
            )
            if non_ascii_equals(status_text, current_status.text):
                self.logger.warning("Skipping status update, nothing to change")
            else:
                expiration_time, expiration_epoch = self.slack.calculate_expiration(
                    track_info.length
                )
                status_emoji = self.slack.pick_emoji(player_name)
                self.logger.info(
                    f"Setting status: {status_emoji}, {status_text}, {expiration_time}"
                )
                self.slack.write_status(status_text, status_emoji, expiration_epoch)

    def handle_stop_playing(self, sender):
        if self.slack.can_update():
            self.logger.info("Clearing status")
            self.slack.write_status("", "", 0)
