#!/usr/bin/env python

import argparse
import datetime
import json
import logging
import os
import time

import dbus
import dbus.mainloop.glib
from dbus.exceptions import DBusException
import requests
from gi.repository import GLib
from yaml import safe_load as load

logging.basicConfig(level=logging.INFO)


class MPRISListener(object):
    __playback_status = "PlaybackStatus"
    __metadata = "Metadata"
    __dbus_interface = "org.freedesktop.DBus.Properties"
    __mpris_interface = "org.mpris.MediaPlayer2."
    __mpris_path = "/org/mpris/MediaPlayer2"

    def __init__(self, track_update_fn, stopped_playing_fn):
        self.track_update_fn = track_update_fn
        self.stopped_playing_fn = stopped_playing_fn
        self.accepted_message_types = [self.__playback_status, self.__metadata]
        self.playing = False
        self.interfaces = {}
        self.logger = logging.getLogger(self.__class__.__name__)

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SessionBus()
        self.build_interfaces()

        self.session_bus = self.bus.get_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus"
        )

        # listen to new and exiting players
        self.session_bus.connect_to_signal(
            "NameOwnerChanged", self.handle_player_connection
        )

        self.run_loop()

    def run_loop(self):
        try:
            loop = GLib.MainLoop()
            loop.run()
        except KeyboardInterrupt:
            loop.quit()

    @classmethod
    def extract_track_info(cls, metadata):
        track_length = metadata.get("mpris:length", 0)
        return {
            "artist": ",".join(metadata.get("xesam:artist", "")),
            "title": str(metadata.get("xesam:title", "")),
            "album": str(metadata.get("xesam:album", "")),
            # convert from microseconds to seconds
            "length": int(track_length / 1000000 if track_length else 0),
        }

    @classmethod
    def strip_mpris(cls, player_name):
        # human friendly name
        return player_name.replace(cls.__mpris_interface, "")

    def track_updated(self, sender, metadata):
        self.playing = True
        track_info = self.extract_track_info(metadata)
        self.logger.info(f"[{sender}] now playing: {track_info}")
        self.track_update_fn(sender, track_info)

    def stopped_playing(self, sender):
        # avoid multiple stop callbacks
        if self.playing:
            self.playing = False
            self.logger.info(f"[{sender}] stopped_playing")
            self.stopped_playing_fn(sender)

    def get_interface(self, service):
        player = self.bus.get_object(service, self.__mpris_path)
        return player.bus_name, dbus.Interface(player, self.__dbus_interface)

    def update_interface(self, player):
        bus_name, interface = self.get_interface(player)
        self.interfaces[bus_name] = {
            "name": self.strip_mpris(player),
            "interface": interface,
        }
        self.connect_signal(bus_name)
        return bus_name

    def find_players(self):
        return (
            player
            for player in self.bus.list_names()
            if player.startswith(self.__mpris_interface)
        )

    def build_interfaces(self):
        for player in self.find_players():
            self.update_interface(player)

    def connect_signal(self, bus_name):
        player = self.interfaces[bus_name]
        player["interface"].connect_to_signal(
            "PropertiesChanged",
            self.handle_properties_changed,
            dbus_interface=self.__dbus_interface,
            sender_keyword="sender",
        )

        self.logger.info(f"[{player['name']}{bus_name}] Connected")

    def handle_player_connection(self, player, old_bus_id, new_bus_id):
        if player.startswith(self.__mpris_interface):
            player_name = self.strip_mpris(player)

            if old_bus_id and not new_bus_id:
                self.logger.info(f"[{player_name}{old_bus_id}] Player exited")

                if self.interfaces.pop(old_bus_id, None):
                    self.stopped_playing(player_name)
                else:
                    self.logger.warning("Player not found: ", player, old_bus_id)

            elif not old_bus_id and new_bus_id:
                self.logger.info(f"[{player_name}{new_bus_id}] Player started")
                self.update_interface(player)

    def handle_properties_changed(
        self, interface_name, message, *args, sender=None, **kwargs
    ):
        if not any(
            message_type in message for message_type in self.accepted_message_types
        ):
            # some players send noise around their capabilities, ignore that
            return

        playing = False
        metadata = None

        try:
            playback_status = message.get(
                self.__playback_status,
                # on Metadata updates, query the interface to get the PlaybackStatus
                self.interfaces[sender]["interface"].Get(
                    interface_name, self.__playback_status
                ),
            )
            playing = playback_status == "Playing"

            if playing:
                # if something is playing, fetch the metadata
                metadata = message.get(
                    self.__metadata,
                    # on PlaybackStatus, query the interface for Metadata
                    self.interfaces[sender]["interface"].Get(
                        interface_name, self.__metadata
                    ),
                )
        except DBusException as err:
            detailed_sender = f"{self.interfaces[sender]['name']}{sender}"
            self.logger.error(
                f"Failed to query player interface. {detailed_sender} might have shutdown: {err}"
            )

        if playing and metadata:
            self.track_updated(self.interfaces[sender]["name"], metadata)
        else:
            self.stopped_playing(self.interfaces[sender]["name"])


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

        self.headers = {"Authorization": f"Bearer {self.token}"}

    @classmethod
    def parse_status(cls, profile):
        return {k: profile[k] for k in profile.keys() & {"status_text", "status_emoji"}}

    @classmethod
    def calculate_expiration(cls, length_seconds):
        expiration_time = datetime.datetime.utcnow() + datetime.timedelta(
            seconds=length_seconds
        )
        return int(time.mktime(expiration_time.timetuple()))

    def handle_track_update(self, sender, track_info):
        current_status = self.can_update()
        if current_status and track_info["artist"] and track_info["title"]:
            status_text = self.__track_message_fmt.format(**track_info)
            status_text = (
                (status_text[: self.__max_status_size] + "...")
                if len(status_text) > self.__max_status_size
                else status_text
            )
            if status_text == current_status["status_text"]:
                self.logger.warning("Skipping status update, nothing to change")
            else:
                self.logger.info(f"Setting status: {self.playing_emoji} {status_text}")
                self.write_status(status_text, self.playing_emoji, track_info["length"])

    def handle_stop_playing(self, sender):
        if self.can_update():
            self.logger.info("Clearing status")
            self.write_status("", "", 0)

    def can_update(self):
        """don't override any other status, based upon the current emoji"""
        current_status = self.read_status()
        current_emoji = current_status["status_emoji"]

        if current_emoji in [self.playing_emoji, ""]:
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        help="YAML configuration file",
        required=False,
        default="config.yaml",
    )
    args = parser.parse_args()

    slack = SlackStatus(os.path.expanduser(args.config))
    listener = MPRISListener(slack.handle_track_update, slack.handle_stop_playing)
