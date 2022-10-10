import logging
import signal
from collections import OrderedDict, namedtuple
from math import ceil

import dbus
import dbus.mainloop.glib
from dbus.exceptions import DBusException
from gi.repository import GLib

MPRIS_INTERFACE = "org.mpris.MediaPlayer2."
DBUS_INTERFACE = "org.freedesktop.DBus.Properties"
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYBACK_STATUS = "PlaybackStatus"
METADATA = "Metadata"

PlayingPlayer = namedtuple("PlayingPlayer", ["bus_id", "player"])


class Player(object):
    def __init__(self, full_name, bus):
        self.full_name = full_name
        self.bus = bus
        self._playback_status = None
        self._playing = False

        self.name = self.strip_mpris(self.full_name)
        self.bus_id, self.interface = self._get_interface(self.full_name)
        self.playback_status = self.query_playback_status()

    @staticmethod
    def strip_mpris(player_name):
        # human friendly name
        return player_name.replace(MPRIS_INTERFACE, "")

    @property
    def playback_status(self):
        return self._playback_status

    @playback_status.setter
    def playback_status(self, status):
        self._playback_status = status
        self._playing = status == "Playing"

    @property
    def playing(self):
        return self._playing

    def query_playback_status(self):
        return self.interface.Get(f"{MPRIS_INTERFACE}Player", PLAYBACK_STATUS)

    def query_metadata(self):
        return self.interface.Get(f"{MPRIS_INTERFACE}Player", METADATA)

    def _get_interface(self, service):
        player = self.bus.get_object(service, MPRIS_PATH)
        return player.bus_name, dbus.Interface(player, DBUS_INTERFACE)

    def __str__(self):
        return self.name

    def __repr__(self) -> str:
        return f"{self.name}{self.bus_id}"


class PlayerManager(object):
    def __init__(self, bus):
        self.bus = bus
        self.players = OrderedDict()
        self.logger = logging.getLogger(self.__class__.__name__)

    def pop(self, bus_id):
        return self.players.pop(bus_id, None)

    def __getitem__(self, bus_id):
        return self.players[bus_id]

    def __setitem__(self, player_name):
        self.update_player(player_name)

    def __delitem__(self, bus_id):
        if bus_id in self.players:
            del self.players[bus_id]

    def __len__(self):
        return len(self.players)

    def move_to_start(self, bus_id):
        self.players.move_to_end(bus_id, last=False)

    def find_first_playing_player(self):
        bus_id, playing_player = next(
            (
                (bus_id, player)
                for bus_id, player in self.players.items()
                if player.playing
            ),
            (None, None),
        )
        if bus_id:
            self.move_to_start(bus_id)

        return PlayingPlayer(bus_id, playing_player)

    def update_player(self, player_name):
        player = Player(player_name, self.bus)
        self.players[player.bus_id] = player

        self.logger.info(
            f"[{player.name}{player.bus_id}] Connected, {player.playback_status}"
        )

        return player


class MPRISListener(object):
    def __init__(self, track_update_fn, stopped_playing_fn):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.track_update_fn = track_update_fn
        self.stopped_playing_fn = stopped_playing_fn
        self.accepted_message_types = [PLAYBACK_STATUS, METADATA]
        self._playing_player = PlayingPlayer(None, None)
        self.exit_signals = [signal.SIGTERM, signal.SIGINT]

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SessionBus()
        self.player_manager = PlayerManager(self.bus)
        self.add_existing_players()
        self.playing_player = self.player_manager.find_first_playing_player()

        # on startup send an update for playing player
        self.send_new_player_update()

        self.session_bus = self.bus.get_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus"
        )

        # listen to new and exiting players
        self.session_bus.connect_to_signal(
            "NameOwnerChanged", self.handle_player_connection
        )

    def run_loop(self):
        loop = GLib.MainLoop()

        def signal_handler(signum, _):
            self.logger.info(f"{signal.strsignal(signum)}: Shutting down...")
            loop.quit()
            self.stopped_playing(self.playing_player.player, exiting=True)

        for exit_signal in self.exit_signals:
            signal.signal(exit_signal, signal_handler)

        loop.run()

    @property
    def playing_player(self):
        return self._playing_player

    @playing_player.setter
    def playing_player(self, playing_player):
        self._playing_player = playing_player
        if playing_player.bus_id:
            self.logger.info(
                f"[{repr(playing_player.player)}] is now active player of {len(self.player_manager)}"
            )
        else:
            self.logger.info(f"No active players of {len(self.player_manager)}")

    @staticmethod
    def extract_track_info(metadata):
        track_length = metadata.get("mpris:length", 0)
        return {
            "artist": ",".join(metadata.get("xesam:artist", "")),
            "title": str(metadata.get("xesam:title", "")),
            "album": str(metadata.get("xesam:album", "")),
            # convert from microseconds to seconds
            "length": int(ceil(track_length / 1000000) if track_length else 0),
        }

    def send_new_player_update(self):
        if self.playing_player.bus_id:
            self.track_updated(
                self.playing_player.player, self.playing_player.player.query_metadata()
            )

    def track_updated(self, player, metadata):
        if self.playing_player.bus_id != player.bus_id:
            # update playing player on track updates, but only if it changes
            self.playing_player = PlayingPlayer(player.bus_id, player)
            self.player_manager.move_to_start(player.bus_id)

        track_info = self.extract_track_info(metadata)
        self.logger.info(f"[{player}] now playing: {track_info}")
        self.track_update_fn(player.name, track_info)

    def stopped_playing(self, player, exiting=False):
        player_bus_id = (
            player.bus_id if player else None
        )  # sometimes player can be None
        matches_playing_player = self.playing_player.bus_id == player_bus_id
        self.logger.info(
            f"[{repr(player)}] stopped playing. matches playing player: {matches_playing_player}"
        )

        # avoid multiple stop callbacks
        if player and matches_playing_player:
            self.stopped_playing_fn(player.name)

        # on exit, do not try to find a new playing player
        if not exiting:
            # if the stopped player matches the playing player find a new playing player
            if matches_playing_player:
                self.playing_player = self.player_manager.find_first_playing_player()
                self.send_new_player_update()

    def find_players(self):
        return (
            player_name
            for player_name in self.bus.list_names()
            if player_name.startswith(MPRIS_INTERFACE)
        )

    def add_existing_players(self):
        for player_name in self.find_players():
            self.connect_signal(self.player_manager.update_player(player_name))

    def connect_signal(self, player):
        player.interface.connect_to_signal(
            "PropertiesChanged",
            self.handle_properties_changed,
            dbus_interface=DBUS_INTERFACE,
            sender_keyword="sender",
        )

    def handle_player_connection(self, player_name, old_bus_id, new_bus_id):
        if player_name.startswith(MPRIS_INTERFACE):
            if old_bus_id and not new_bus_id:
                old_player = self.player_manager.pop(old_bus_id)
                if old_player:
                    self.stopped_playing(old_player)
                    self.logger.info(f"[{repr(old_player)}] Player exited")
                else:
                    self.logger.warning(
                        "Exiting player not found: ", player_name, old_bus_id
                    )

            elif not old_bus_id and new_bus_id:
                new_player = self.player_manager.update_player(player_name)
                self.logger.info(f"[{repr(new_player)}] Player started")
                self.connect_signal(new_player)

    def handle_properties_changed(
        self, interface_name, message, *args, sender, **kwargs
    ):
        if not any(
            message_type in message for message_type in self.accepted_message_types
        ):
            # some players send noise around their capabilities, ignore that
            return

        player = self.player_manager[sender]
        metadata = None

        try:
            # on Metadata updates, query the interface to get the PlaybackStatus
            player.playback_status = message.get(
                PLAYBACK_STATUS, player.query_playback_status()
            )

            if player.playing:
                # if something is playing, fetch the metadata
                metadata = message.get(
                    METADATA,
                    # on PlaybackStatus, query the interface for Metadata
                    player.query_metadata(),
                )
        except DBusException as err:
            self.logger.error(
                f"Failed to query player interface. {repr(player)} might have shutdown: {err}"
            )

        if player.playing and metadata:
            self.track_updated(player, metadata)
        else:
            self.stopped_playing(player)
