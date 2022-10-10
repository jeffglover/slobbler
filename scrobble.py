import datetime
import json
import logging
import os
from calendar import timegm
from random import choice, seed

import requests
from yaml import safe_load as load


def remove_non_ascii(string):
    return string.encode("ascii", errors="ignore").decode()


class SlackStatus(object):
    __slack_api_fmt = "https://slack.com/api/{command}"
    __track_message_fmt = "{artist} - {title}"
    __max_status_size = 97

    def __init__(self, config_file):
        self.logger = logging.getLogger(self.__class__.__name__)
        assert os.path.isfile(config_file), f"not a file: {config_file}"

        with open(config_file, "r") as fh:
            config = load(fh)

        self.token = config["user_oauth_token"]
        self.user_id = config["user_id"]
        self.playing_emoji = config["playing_emoji"]
        self.fallback_emojis = self.playing_emoji["fallback"]  # must have at least one
        self.valid_playing_emojis = ["", *self.fallback_emojis]  # empty is valid

        # add player specific emojis
        self.valid_playing_emojis.extend(
            (
                emoji
                for player, emoji in self.playing_emoji.items()
                if player != "fallback"
            )
        )
        self.headers = {"Authorization": f"Bearer {self.token}"}
        seed()

    @staticmethod
    def parse_status(profile):
        return {k: profile[k] for k in profile.keys() & {"status_text", "status_emoji"}}

    @staticmethod
    def calculate_expiration(length_seconds):
        if length_seconds:
            expiration_time = datetime.datetime.utcnow() + datetime.timedelta(
                seconds=length_seconds
            )
            return expiration_time, timegm(expiration_time.timetuple())
        return None, 0

    def handle_track_update(self, player_name, track_info):
        current_status = self.can_update()
        if current_status and track_info["artist"] and track_info["title"]:
            status_text = self.__track_message_fmt.format(**track_info)
            status_text = (
                (status_text[: self.__max_status_size] + "...")
                if len(status_text) > self.__max_status_size
                else status_text
            )
            if remove_non_ascii(status_text) == remove_non_ascii(
                current_status["status_text"]
            ):
                self.logger.warning("Skipping status update, nothing to change")
            else:
                expiration_time, expiration_epoch = self.calculate_expiration(
                    track_info["length"]
                )
                status_emoji = self.playing_emoji.get(
                    player_name,  # try player name specific emoji
                    choice(
                        self.fallback_emojis
                    ),  # fallback to a random choice of fallback emojis
                )
                self.logger.info(
                    f"Setting status: {status_emoji}, {status_text}, {expiration_time}"
                )
                self.write_status(
                    status_text,
                    status_emoji,
                    expiration_epoch,
                )

    def handle_stop_playing(self, sender):
        if self.can_update():
            self.logger.info("Clearing status")
            self.write_status("", "", 0)

    def can_update(self):
        """don't override any other status, based upon the current emoji"""
        current_status = self.read_status()
        current_emoji = current_status["status_emoji"]

        if current_emoji in self.valid_playing_emojis:
            return current_status

        self.logger.info(f"Cannot update because emoji is set: {current_emoji}")
        return False

    def read_status(self):
        params = {"user": self.user_id}
        response = requests.get(
            self.__slack_api_fmt.format(command="users.profile.get"),
            headers=self.headers,
            params=params,
        )
        assert response.ok, f"Bad response from server [{response}]: {response.text}"

        json_response = response.json()
        assert json_response["ok"], f"Failed because {json_response['error']}"
        return self.parse_status(json_response["profile"])

    def write_status(self, message, emoji, expiration=0):
        headers = {
            **self.headers,
            "Content-Type": "application/json; charset=utf-8",
        }
        params = {"user": self.user_id}
        status_payload = {
            "profile": {
                "status_text": message,
                "status_emoji": emoji,
                "status_expiration": expiration,
            }
        }

        response = requests.post(
            self.__slack_api_fmt.format(command="users.profile.set"),
            headers=headers,
            params=params,
            data=json.dumps(status_payload).encode("utf-8"),
        )
        assert response.ok, f"Bad response from server [{response}]: {response.text}"

        json_response = response.json()
        assert json_response["ok"], f"Failed because {json_response['error']}"
        return self.parse_status(json_response["profile"])
