import logging
import signal
import typing as typ
from collections import OrderedDict
from dataclasses import dataclass
from math import ceil
from pprint import pformat

import dbus
import dbus.mainloop.glib
from dbus.exceptions import DBusException
from gi.repository import GLib

from .constants import (
    DBUS_ERROR_UNKNOWN_METHOD,
    DBUS_INTERFACE,
    METADATA,
    MPRIS_INTERFACE,
    MPRIS_PARTIAL_INTERFACE,
    MPRIS_PATH,
    PLAYBACK_STATUS,
)

DBUS_DICT_TYPE = typ.MutableMapping[dbus.String, typ.Any]
ANY_PRIMITIVE = str | int | float | bool


@dataclass
class TrackInfo:
    artist: str
    title: str
    album: str
    length: int

    @classmethod
    def from_mpris(cls, metadata: DBUS_DICT_TYPE):
        track_length = metadata.get("mpris:length", 0)
        return cls(
            artist=",".join(metadata.get("xesam:artist", [""])),  # array expected
            title=str(metadata.get("xesam:title", "")),
            album=str(metadata.get("xesam:album", "")),
            # convert from microseconds to seconds
            length=int(ceil(track_length / 1000000) if track_length else 0),
        )

    def to_dict(self) -> typ.Dict[str, ANY_PRIMITIVE]:
        return {
            "artist": self.artist,
            "title": self.title,
            "album": self.album,
            "length": self.length,
        }

    def __str__(self):
        return f"artist='{self.artist}' title='{self.title}' album='{self.album}' length={self.length}s"


class Player:
    def __init__(
        self,
        full_name: str,
        bus: dbus.SessionBus,
        playback_status_changed_fn: typ.Callable[[str], None],
        metadata_update_fn: typ.Callable[[str], None],
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.full_name = full_name
        self._bus = bus

        self.playback_status_changed_fn = playback_status_changed_fn
        self.metadata_update_fn = metadata_update_fn

        self._playback_status = "Stopped"
        self._playing: bool = False
        self._track_info = None
        self.accepted_message_types = (PLAYBACK_STATUS, METADATA)

        self.name = self.strip_mpris(self.full_name)
        self.bus_id, self.interface = self._get_interface(self.full_name)
        self.playback_status = self.query_playback_status()
        if self.playing:
            self.track_info = self.query_metadata()

        self._signal_connection = self.connect_signal()

    def __del__(self):
        self.close()

    def close(self):
        self._signal_connection.remove()

    @staticmethod
    def strip_mpris(player_name: str) -> str:
        # human friendly name
        return player_name.replace(MPRIS_PARTIAL_INTERFACE, "")

    @property
    def playback_status(self):
        return self._playback_status

    @playback_status.setter
    def playback_status(self, status: dbus.String):
        self._playback_status = str(status)
        self._playing = status == "Playing"

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def track_info(self) -> TrackInfo:
        return self._track_info

    @track_info.setter
    def track_info(self, metadata: DBUS_DICT_TYPE):
        self._track_info = TrackInfo.from_mpris(metadata)

    def handle_properties_changed(
        self, interface_name, message: DBUS_DICT_TYPE, *args, **kwargs
    ):
        if not any(
            message_type in message for message_type in self.accepted_message_types
        ):
            # some players send noise around their capabilities, ignore that
            return

        self.logger.debug(
            f"handle_properties_changed(): [{repr(self)}] message: {type(message)}, {pformat(dict(message), indent=2)}"
        )
        metadata: DBUS_DICT_TYPE | None = message.get(METADATA)
        playback_status: str | None = message.get(PLAYBACK_STATUS)

        if metadata:
            self.track_info = metadata
            if self.playing:
                self.metadata_update_fn(self.bus_id)
        elif playback_status:
            self.playback_status = playback_status
            if self.playing:
                # some players, notably Spotify, don't update metadata from startup -> playing
                self.track_info = self.query_metadata()
            self.playback_status_changed_fn(self.bus_id)

    def connect_signal(self) -> dbus.connection.SignalMatch:
        return self.interface.connect_to_signal(
            "PropertiesChanged",
            self.handle_properties_changed,
            dbus_interface=DBUS_INTERFACE,
        )

    def query_playback_status(self) -> dbus.types.String:
        try:
            return self.interface.Get(MPRIS_INTERFACE, PLAYBACK_STATUS)
        except DBusException as err:
            # some players don't have PlaybackStatus on startup
            if err.get_dbus_name() == DBUS_ERROR_UNKNOWN_METHOD:
                self.logger.error(f"[{repr(self)}]: Unable to query {PLAYBACK_STATUS}")
                return "Stopped"
            raise err

    def query_metadata(self) -> DBUS_DICT_TYPE:
        try:
            return self.interface.Get(MPRIS_INTERFACE, METADATA)
        except DBusException as err:
            if err.get_dbus_name() == DBUS_ERROR_UNKNOWN_METHOD:
                self.logger.error(f"[{repr(self)}]: Unable to query {METADATA}")
                return {}
            raise err

    def _get_interface(self, service: str) -> tuple[str, dbus.Interface]:
        player = self._bus.get_object(service, MPRIS_PATH)
        return str(player.bus_name), dbus.Interface(player, DBUS_INTERFACE)

    def __str__(self):
        return self.name

    def __repr__(self) -> str:
        return f"{self.name}{self.bus_id}"


class PlayerManager:
    def __init__(
        self,
        player_update_fn: typ.Callable[[Player], None],
        player_stopped_fn: typ.Callable[[Player], None],
    ):
        self._bus = dbus.SessionBus()
        self.player_update_fn = player_update_fn
        self.player_stopped_fn = player_stopped_fn

        self.players: typ.OrderedDict[str, Player] = OrderedDict()
        self.logger = logging.getLogger(self.__class__.__name__)

        self.add_existing_players()
        self.playing_player_id = self.find_first_playing_player()
        self.send_new_player_update()

        self._session_bus = self._bus.get_object(
            "org.freedesktop.DBus", "/org/freedesktop/DBus"
        )

        # listen to new and exiting players
        self._signal_connection = self._session_bus.connect_to_signal(
            "NameOwnerChanged", self.handle_player_connection
        )

    def __del__(self):
        self.close()

    def close(self):
        self._signal_connection.remove()

    def handle_player_connection(
        self, player_name: str, old_bus_id: str, new_bus_id: str
    ):
        if player_name.startswith(MPRIS_PARTIAL_INTERFACE):
            self.logger.debug(
                f"handle_player_connection({player_name=} {old_bus_id=} {new_bus_id=})"
            )
            if old_bus_id and not new_bus_id:
                old_player = self.pop(old_bus_id)
                if old_player:
                    self.logger.info(f"[{repr(old_player)}] Player exited")
                    self.handle_player_not_playing(old_player)
                else:
                    self.logger.warning(
                        "Exiting player not found: ", player_name, old_bus_id
                    )

            elif not old_bus_id and new_bus_id:
                new_player = self.update_player(player_name)
                self.logger.info(f"[{repr(new_player)}] Player started")

    def handle_player_not_playing(self, player: Player):
        self.playing_player_id = self.find_first_playing_player()
        if not self.send_new_player_update():
            self.player_stopped_fn(player)

    def find_first_playing_player(self) -> str:
        bus_id = next(
            (bus_id for bus_id, player in self.players.items() if player.playing),
            None,
        )
        if bus_id:
            self.move_to_start(bus_id)

        return bus_id

    def update_player(self, player_name: str) -> Player:
        player = Player(
            player_name, self._bus, self.playback_status_changed, self.metadata_update
        )
        self.players[player.bus_id] = player

        self.logger.info(
            f"[{player.name}{player.bus_id}] Connected, {player.playback_status}"
        )

        return player

    def send_new_player_update(self) -> bool:
        if self.playing_player_id:
            self.player_update_fn(self[self.playing_player_id])
            return True
        return False

    def playback_status_changed(self, bus_id: str):
        player = self[bus_id]
        self.logger.debug(
            f"[{player}] playback_status_changed() {player.playback_status=}, {self.playing_player_id=}"
        )
        if player.playing and bus_id != self.playing_player_id:
            # new playing player detected
            self.move_to_start(bus_id)
            self.playing_player_id = bus_id
            self.player_update_fn(player)

        elif not player.playing and bus_id == self.playing_player_id:
            # playing player has stopped playing
            self.handle_player_not_playing(player)

    def metadata_update(self, bus_id: str):
        player = self[bus_id]
        self.logger.debug(
            f"[{player}]: metadata_update() {player.playback_status=}, {player.track_info=}"
        )

        if player.playing and bus_id == self.playing_player_id:
            self.player_update_fn(player)

    def find_players(self) -> typ.Generator[str, None, None]:
        return (
            str(player_name)
            for player_name in self._bus.list_names()
            if player_name.startswith(MPRIS_PARTIAL_INTERFACE)
        )

    def add_existing_players(self):
        for player_name in self.find_players():
            self.update_player(player_name)

    def move_to_start(self, bus_id: str):
        self.players.move_to_end(bus_id, last=False)

    def pop(self, bus_id: str) -> Player | None:
        player = self.players.pop(bus_id, None)
        if player:
            player.close()

        return player

    def __getitem__(self, bus_id: str):
        return self.players[bus_id]

    def __setitem__(self, player_name: str):
        self.update_player(player_name)

    def __delitem__(self, bus_id: str):
        self.pop(bus_id)

    def __len__(self):
        return len(self.players)


class MPRISListener:
    def __init__(
        self,
        track_update_fn: typ.Callable[[str, TrackInfo], None],
        stopped_playing_fn: typ.Callable[[str], None],
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.track_update_fn = track_update_fn
        self.stopped_playing_fn = stopped_playing_fn
        self.exit_signals = (signal.SIGTERM, signal.SIGINT)

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.player_manager = PlayerManager(self.track_updated, self.stopped_playing)

    def run_loop(self):
        loop = GLib.MainLoop()

        def signal_handler(signum, _):
            self.logger.info(f"{signal.strsignal(signum)}: Shutting down...")
            loop.quit()
            self.player_manager.close()
            self.stopped_playing_fn("shutdown")

        for exit_signal in self.exit_signals:
            signal.signal(exit_signal, signal_handler)

        loop.run()

    def track_updated(self, player: Player):
        self.track_update_fn(player.name, player.track_info)

    def stopped_playing(self, player: Player):
        self.stopped_playing_fn(player.name)
