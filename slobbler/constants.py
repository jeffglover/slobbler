__all__ = [
    "MPRIS_PARTIAL_INTERFACE",
    "MPRIS_INTERFACE",
    "DBUS_INTERFACE",
    "MPRIS_PATH",
    "PLAYBACK_STATUS",
    "METADATA",
    "DBUS_ERROR_UNKNOWN_METHOD",
]


MPRIS_PARTIAL_INTERFACE = "org.mpris.MediaPlayer2."
MPRIS_INTERFACE = MPRIS_PARTIAL_INTERFACE + "Player"
DBUS_INTERFACE = "org.freedesktop.DBus.Properties"
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYBACK_STATUS = "PlaybackStatus"
METADATA = "Metadata"
DBUS_ERROR_UNKNOWN_METHOD = "org.freedesktop.DBus.Error.UnknownMethod"
