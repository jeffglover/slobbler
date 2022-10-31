# slobbler

Slack status music scrobbler for Linux. Updates slack status based upon any media player using the [MPRIS DBus Protocol](https://specifications.freedesktop.org/mpris-spec/latest/)

# Features

- Connects to all players, publishes only the playing one
- Clears status on pause or player exit
- Choose emoji based upon player names
- For fallback players, randomly chooses from a list
- Only updates Slack status if no status or already playing is set. Won't override an existing status. Detection based upon the status emoji
- Filters when track is missing artist info, likely a video on a webpage

## Installation

`$ pip install --user git+https://github.com/jeffglover/slobbler.git`

## Configuration

Create a config file `~/.config/slobbler.yaml`:

```yaml
slobbler:
  user_id: U0123456
  user_oauth_token: xoxp-token
  playing_emoji:
    spotify: ":spotify:"
    fallback: [":notes:", ":the_horns:", ":headphones:"]
```

## Configuring Slobbler as a Slack App

1. Add slobbler to [Slack Apps](https://api.slack.com/apps)
2. Click `Create New App`
3. Choose `From scratch`
4. App Name -> `Slobber` and choose your workspace
5. Click `Create App`
6. Click `Add features and functionality`
7. Choose `Permissions`
8. Click `Add on OAuth Scope` and add `emoji:read`, `users.profile:read`, `users.profile:write`
9. Copy `User OAuth Token` use that as `user_oauth_token` in slobbler config
10. Go back to `Basic Information`
11. Install your app -> `Install to Workspace` and `Allow` permissions

## Running

`$ slobbler --config ~/.config/slobbler.yaml`

## systemd

Use systemd to keep it running in the background

`~/.config/systemd/user/slobbler.service`

```
[Unit]
Description=Slack status scrobbler
After=network.target
After=dbus.socket
Requires=dbus.socket

[Service]
ExecStart=<path to bin>/slobbler --config ~/.config/slobbler.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

`systemctl --user enable --now slobbler.service`

## TODOs

- [ ] Better and configurable filtering
  - Track/Artist name
  - Player name
  - If it's a browser, can I tell what website it's on?

## Useful references

- [MPRIS Slack Integration](https://github.com/curtisgibby/mpris-slack-python)
  Good starting place for me, helped with figuring out how to work with DBus/MPRIS. This must be run after a player is playing. Won't handle players exiting or starting.
- [Linux: Spotify Track Notifier](https://muffinresearch.co.uk/linux-spotify-track-notifier-with-added-d-bus-love/)
  Helpful reference when working with DBus/MPRIS. Only works with Spotify and doesn't do anything with Slack
- [dbus-python tutorial](https://dbus.freedesktop.org/doc/dbus-python/tutorial.html)
- [dbus-python examples](https://gitlab.freedesktop.org/dbus/dbus-python/-/tree/master/examples)
