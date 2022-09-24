#!/usr/bin/env python

from gi.repository import GLib

import dbus
import dbus.mainloop.glib

from pprint import pp

"""
https://github.com/curtisgibby/mpris-slack-python/blob/master/mpris-track-change-to-slack.py
https://dbus.freedesktop.org/doc/dbus-python/tutorial.html#signal-matching
https://gitlab.freedesktop.org/dbus/dbus-python/-/blob/master/examples/example-async-client.py
https://muffinresearch.co.uk/linux-spotify-track-notifier-with-added-d-bus-love/


maybe try this https://github.com/altdesktop/playerctl/blob/master/examples/basic-example.py
"""


class MPRISListener(object):
    PLAYBACK_STATUS = "PlaybackStatus"
    METADATA = "Metadata"

    def __init__(self, accepted_message_types=[PLAYBACK_STATUS, METADATA]):
        self.accepted_message_types = accepted_message_types
        self.interfaces = {}
        self.playing = False

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SessionBus()
        self.build_interfaces()

        self.session_bus = self.bus.get_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus"
        )
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

    @staticmethod
    def track_updated_callback(sender, track_info):
        print(f"[{sender}] now playing: {track_info}")

    @staticmethod
    def stopped_playing_callback(sender):
        print(f"[{sender}] stopped_playing")

    @staticmethod
    def strip_mpris(player_name):
        return player_name.replace("org.mpris.MediaPlayer2.", "")

    @staticmethod
    def extract_track_info(metadata):
        return {
            "artist": ",".join(metadata["xesam:artist"]),
            "title": str(metadata["xesam:title"]),
            "album": str(metadata["xesam:album"]),
        }

    def get_interface(self, service):
        player = self.bus.get_object(service, "/org/mpris/MediaPlayer2")
        return player.bus_name, dbus.Interface(
            player, "org.freedesktop.DBus.Properties"
        )

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
            if player.startswith("org.mpris.MediaPlayer2")
        )

    def build_interfaces(self):
        for player in self.find_players():
            self.update_interface(player)

    def connect_signal(self, bus_name):
        player = self.interfaces[bus_name]
        player["interface"].connect_to_signal(
            "PropertiesChanged",
            self.handle_properties_changed,
            dbus_interface="org.freedesktop.DBus.Properties",
            sender_keyword="sender",
        )

        print(f"[{player['name']}{bus_name}] Connected")

    def handle_player_connection(self, player, old_bus_id, new_bus_id):
        if player.startswith("org.mpris.MediaPlayer2"):
            player_name = self.strip_mpris(player)

            if old_bus_id and not new_bus_id:
                print(f"[{player_name}{old_bus_id}] Player exited")

                if self.interfaces.pop(old_bus_id, None):
                    self.stopped_playing_callback(player_name)
                else:
                    print("Player not found: ", player, old_bus_id)

            elif not old_bus_id and new_bus_id:
                print(f"[{player_name}{new_bus_id}] Player started")
                self.update_interface(player)

    def handle_properties_changed(
        self, interface_name, message, *args, sender=None, **kwargs
    ):
        if not any(
            message_type in message for message_type in self.accepted_message_types
        ):
            return

        metadata = None
        playback_status = message.get(
            self.PLAYBACK_STATUS,
            self.interfaces[sender]["interface"].Get(
                interface_name, self.PLAYBACK_STATUS
            ),
        )
        playing = playback_status == "Playing"

        if playing:
            # if something is playing, fetch the metadata
            metadata = message.get(
                self.METADATA,
                # on PlaybackStatus we have to query the interface for Metadata
                self.interfaces[sender]["interface"].Get(interface_name, self.METADATA),
            )

        if playing and metadata:
            self.playing = True
            track_info = self.extract_track_info(metadata)
            self.track_updated_callback(self.interfaces[sender]["name"], track_info)
        else:
            if self.playing:
                # avoid multiple stop callbacks
                self.stopped_playing_callback(self.interfaces[sender]["name"])
                self.playing = False


if __name__ == "__main__":
    listener = MPRISListener()
