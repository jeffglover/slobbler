#!/usr/bin/env python
import gi

gi.require_version("Playerctl", "2.0")

from gi.repository import Playerctl, GLib
import dbus.mainloop.glib

from pprint import pp


def extract_track_info(metadata_obj):
    metadata = dict(metadata_obj)
    track_info = {}
    if metadata:
        track_info = {
            "album": metadata.get("xesam:album"),
            "artist": ",".join(metadata.get("xesam:artist", "")),
            "title": metadata.get("xesam:title"),
        }
    return track_info


def on_metadata(player, metadata):
    track_info = extract_track_info(metadata)
    print("Now playing:")
    pp(track_info)


def on_play(player, status):
    pp(player.props.metadata)
    track_info = extract_track_info(player.props.metadata)
    print("Now playing:")
    pp(track_info)


def on_pause(player, status):
    print("Paused the song: {}".format(player.get_title()))


def on_name_appeared(player):
    print("player has started: {}".format(player.props.player_name))


def on_player_vanished(player):
    print("player has exited: {}".format(player.props.player_name))


if __name__ == "__main__":
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    player = Playerctl.Player()
    # player.connect("player-vanished", on_player_vanished)
    # player.connect("name-appeared", on_name_appeared)
    player.connect("exit", on_player_vanished)
    player.connect("playback-status::playing", on_play)
    player.connect("playback-status::paused", on_pause)
    player.connect("metadata", on_metadata)

    # wait for events
    main = GLib.MainLoop()
    main.run()
