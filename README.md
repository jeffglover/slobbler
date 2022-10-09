# slobbler

Slack status scrobbler. Updates slack status based upon any media player using the [MPRIS DBus Protocol](https://specifications.freedesktop.org/mpris-spec/latest/)

# Features

- Connects to all players, publishes only the playing one
- Clears status on pause or player exit
- Only updates Slack status if no status or already playing is set. Won't override an existing status. Detection based upon the status emoji
- Filters when track is missing artist info, likely a video on a webpage

### Configuration

Create a config file `~/.config/slobbler.yaml`:

```yaml
user_id: U123456 # user id from slack
user_oauth_token: xoxp-token # oauth token from your slack app configuration
playing_emoji:
  spotify: ":spotify:" # player specific is optional
  fallback: [":notes:", ":catjam:", ":headphones:"] # must be at lest one
```

### Running

`./slobbler.py --config ~/.config/slobbler.yaml`

### systemd

Use systemd to keep it running in the background

`~/.config/systemd/user/slobbler.service`

```
[Unit]
Description=Slack status scrobbler
After=network.target
After=dbus.socket
Requires=dbus.socket

[Service]
ExecStart=<path to project>/slobbler.py --config ~/.config/slobbler.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

`systemctl --user enable --now slobbler.service`

# Dependencies

Assumptions are made that a Linux system with a modern Desktop Environment will have DBus based dependencies and requests. TODO covers better dependency management as a Python package.

# TODOs

- [ ] Make this a Python package
- [x] Status icon based upon Player with fallback generic, e.g., if spotify use :spotify: emoji
- [x] Fallback icon chosen from a random list of playing icons
- [ ] Better and configurable filtering
  - Track/Artist name
  - Player name
  - If it's a browser, can I tell what website it's on?
- [x] Better detection of playing players after more than one starts playing (toggle play/pause to fix it isn't a big deal)

# Useful references

- [MPRIS Slack Integration](https://github.com/curtisgibby/mpris-slack-python)
  Good starting place for me, helped with figuring out how to work with DBus/MPRIS. This must be run after a player is playing. Won't handle players exiting or starting.
- [Linux: Spotify Track Notifier](https://muffinresearch.co.uk/linux-spotify-track-notifier-with-added-d-bus-love/)
  Helpful reference when working with DBus/MPRIS. Only works with Spotify and doesn't do anything with Slack
- [dbus-python tutorial](https://dbus.freedesktop.org/doc/dbus-python/tutorial.html)
- [dbus-python examples](https://gitlab.freedesktop.org/dbus/dbus-python/-/tree/master/examples)
