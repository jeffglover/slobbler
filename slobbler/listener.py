import logging
import signal
import typing as typ
from collections import OrderedDict
from dataclasses import dataclass, fields
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

    def empty_fields(self) -> typ.Generator[str, None, None]:
        return (field.name for field in fields(self) if not self[field.name])

    def __getitem__(self, attribute: str):
        return getattr(self, attribute)

    def __str__(self):
        return f"artist='{self.artist}' title='{self.title}' album='{self.album}' length={self.length}s"


class Player:
    def __init__(
        self,
        full_name: str,
        bus: dbus.SessionBus,
        playback_status_changed_callback: typ.Callable[[str], None],
        metadata_update_callback: typ.Callable[[str], None],
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._full_name: str = ""
        self._name: str = ""
        self._playback_status: str = "Stopped"
        self._playing: bool = False
        self._track_info: TrackInfo | None = None
        self._track_info_changed: bool = False
        self.accepted_message_types = (PLAYBACK_STATUS, METADATA)
        self.bus_id = None
        self.interface = None
        self._signal_connection = None

        self._bus = bus
        self.full_name = full_name
        self.playback_status_changed_callback = playback_status_changed_callback
        self.metadata_update_callback = metadata_update_callback

    def connect(self):
        self.bus_id, self.interface = self._get_interface(self.full_name)
        self.playback_status = self.query_playback_status()
        if self.playing:
            self.track_info = self.query_metadata()

        self._signal_connection = self.connect_signal()

    def __del__(self):
        self.close()

    def close(self):
        if self._signal_connection:
            self._signal_connection.remove()

    @staticmethod
    def strip_mpris(player_name: str) -> str:
        # human friendly name
        return player_name.replace(MPRIS_PARTIAL_INTERFACE, "")

    @property
    def full_name(self) -> str:
        return self._full_name

    @full_name.setter
    def full_name(self, full_name: str):
        self._full_name = full_name
        self._name = self.strip_mpris(self._full_name)

    @property
    def name(self) -> str:
        return self._name

    @property
    def playback_status(self) -> str:
        return self._playback_status

    @playback_status.setter
    def playback_status(self, status: dbus.String):
        self._playback_status = str(status)
        self._playing = status == "Playing"
        self.logger.info(f"[{self}] playback status changed: {self.playback_status}")

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def track_info(self) -> TrackInfo | None:
        return self._track_info

    @track_info.setter
    def track_info(self, metadata: DBUS_DICT_TYPE):
        new_track_info = TrackInfo.from_mpris(metadata)
        self._track_info_changed = self._track_info != new_track_info
        self._track_info = new_track_info
        if self.track_info_changed:
            self.logger.info(f"[{self}] metadata update: {self.track_info}")

    @property
    def track_info_changed(self) -> bool:
        return self._track_info_changed

    def handle_properties_changed(
        self, interface_name, message: DBUS_DICT_TYPE, *args, **kwargs
    ):
        if not any(
            message_type in message for message_type in self.accepted_message_types
        ):
            # some players send noise around their capabilities, ignore that
            return

        self.logger.debug(
            f"handle_properties_changed(): [{repr(self)}]: {pformat(dict(message), indent=2)}"
        )
        metadata: DBUS_DICT_TYPE | None = message.get(METADATA)
        playback_status: str | None = message.get(PLAYBACK_STATUS)

        if metadata:
            self.track_info = metadata
            if self.playing and self.track_info_changed:
                self.metadata_update_callback(self.bus_id)

        elif playback_status:
            self.playback_status = playback_status
            if self.playing:
                # some players, notably Spotify, don't update metadata from startup -> playing
                self.track_info = self.query_metadata()
            self.playback_status_changed_callback(self.bus_id)

    def connect_signal(self) -> dbus.connection.SignalMatch:
        return self.interface.connect_to_signal(
            "PropertiesChanged",
            self.handle_properties_changed,
            dbus_interface=DBUS_INTERFACE,
        )

    def query_playback_status(self) -> dbus.types.String:
        return self.query_interface(PLAYBACK_STATUS, "Stopped")

    def query_metadata(self) -> DBUS_DICT_TYPE:
        return self.query_interface(METADATA, {})

    def query_interface(self, query_method: str, default: typ.Any):
        try:
            return self.interface.Get(MPRIS_INTERFACE, query_method)
        except DBusException as err:
            # some players don't have some methods on startup
            if err.get_dbus_name() == DBUS_ERROR_UNKNOWN_METHOD:
                self.logger.error(f"[{repr(self)}]: Unable to query {query_method}")
                return default
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
        ignore_players: typ.Iterable[str],
        player_update_callback: typ.Callable[[Player], None],
        player_stopped_callback: typ.Callable[[Player], None],
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._bus = dbus.SessionBus()
        self.ignore_players = tuple(ignore_players)
        self.player_update_callback = player_update_callback
        self.player_stopped_callback = player_stopped_callback

        self.players: typ.OrderedDict[str, Player] = OrderedDict()
        self.playing_player_id = None
        self.add_existing_players()

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
                if old_player and old_player.bus_id == self.playing_player_id:
                    # if exiting player is playing, handle it
                    # otherwise, we don't care
                    self.handle_player_not_playing(old_player)
                elif not old_player:
                    self.logger.warning(
                        "Exiting player not found: ", player_name, old_bus_id
                    )

            elif not old_bus_id and new_bus_id:
                self.update_player(player_name)

    def playback_status_changed(self, bus_id: str):
        player = self[bus_id]
        self.logger.debug(
            f"[{player}] playback_status_changed() {player.playback_status=}, {player.bus_id}, {self.playing_player_id=}"
        )
        if player.playing and bus_id != self.playing_player_id:
            # new playing player detected
            self.handle_new_playing_player(bus_id)

        elif not player.playing and bus_id == self.playing_player_id:
            # playing player has stopped playing
            self.handle_player_not_playing(player)

    def metadata_update(self, bus_id: str):
        player = self[bus_id]
        self.logger.debug(
            f"[{player}]: metadata_update() {player.playback_status=}, {player.track_info=}"
        )

        if player.playing and bus_id == self.playing_player_id:
            self.player_update_callback(player)

    def handle_player_not_playing(self, player: Player):
        self.playing_player_id = self.find_first_playing_player()
        if not self.send_new_player_update():
            self.player_stopped_callback(player)

    def handle_new_playing_player(self, bus_id: str):
        self.playing_player_id = bus_id
        self.move_to_start(self.playing_player_id)
        self.send_new_player_update()

    def find_first_playing_player(self) -> str:
        bus_id = next(
            (bus_id for bus_id, player in self.players.items() if player.playing),
            None,
        )
        if bus_id:
            self.move_to_start(bus_id)
        else:
            self.logger.info(f"No playing players of {len(self)}")

        return bus_id

    def update_player(self, player_name: str) -> Player:
        player = Player(
            player_name, self._bus, self.playback_status_changed, self.metadata_update
        )
        if any(ignore_player in player.name for ignore_player in self.ignore_players):
            self.logger.info(f"Ignoring player: {player.name}")
            return

        player.connect()
        self.players[player.bus_id] = player

        self.logger.info(f"[{repr(player)}] Connected, {player.playback_status}")

        if player.playing:
            # in case a player starts up playing
            self.handle_new_playing_player(player.bus_id)

    def send_new_player_update(self) -> bool:
        if self.playing_player_id:
            self.player_update_callback(self[self.playing_player_id])
            return True
        return False

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
            self.logger.info(f"[{repr(player)}] Disconnected, {player.playback_status}")

        return player

    def __getitem__(self, bus_id: str):
        return self.players[bus_id]

    def __delitem__(self, bus_id: str):
        self.pop(bus_id)

    def __len__(self):
        return len(self.players)


class MPRISListener:
    def __init__(
        self,
        config: typ.Dict[str, typ.Any],
        track_update_callback: typ.Callable[[str, TrackInfo], None],
        stopped_playing_callback: typ.Callable[[str], None],
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.track_update_callback = track_update_callback
        self.stopped_playing_callback = stopped_playing_callback
        self.exit_signals = (signal.SIGTERM, signal.SIGINT)

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.player_manager = PlayerManager(
            config.get("ignore", []), self.track_updated, self.stopped_playing
        )

    def run_loop(self):
        loop = GLib.MainLoop()

        def signal_handler(signum, _):
            self.logger.info(f"{signal.strsignal(signum)}: Shutting down...")
            loop.quit()
            self.player_manager.close()
            self.stopped_playing_callback("shutdown")

        for exit_signal in self.exit_signals:
            signal.signal(exit_signal, signal_handler)

        loop.run()

    def track_updated(self, player: Player):
        self.track_update_callback(player.name, player.track_info)

    def stopped_playing(self, player: Player):
        self.stopped_playing_callback(player.name)
