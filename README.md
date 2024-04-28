# slobbler

Slack status music scrobbler for Linux. Updates slack status based upon any media player using the [MPRIS DBus Protocol](https://specifications.freedesktop.org/mpris-spec/latest/)

# Features

- Connects to all players, publishes only the playing one
- Clears status on pause or player exit
- Choose emoji based upon player names
  - For fallback players, randomly chooses from a list
- Only updates Slack status if no status or already playing is set. Won't override an existing status. Detection based upon the status emoji
- Configurable required fields (e.g., must have artist and title)
- Configurable filters on track metadata (artist, title, album), similar format to exceptions, see Advanced config
- Exceptions to filters and required fields, allow scrobble even when it does not have required fields or filter matches
  - Choose field and partial text match, along with custom message format and emoji
    ```yaml
    exceptions:
      - field: "title"
        partial: "Udemy"
        emoji: ":male-student:"
        message_format: "Learning: {title}"
    ```
    If I'm watching a Udemy course, update status with custom emoji and message

## Installation

`$ pip install --user git+https://github.com/jeffglover/slobbler.git`

## Configuration

Create a config file `~/.config/slobbler.yaml`:

### Basic config

```yaml
slack:
  user_id: U0123456
  user_oauth_token: xoxp-token

slobbler:
  default_emojis:
    - ":notes:"
```

### Advanced config

```yaml
slack:
  user_id: U0123456
  user_oauth_token: xoxp-token

slobbler:
  # Custom message format, defaults to "{artist} - {title}"
  message_format: "{artist} - {title}"
  player_emojis:
    # exact match emoji to a specific player
    spotify: ":spotify:"

  default_emojis:
    # random choice of emojis when doesn't match player emoji, must have at least one
    - ":notes:"
    - ":the_horns:"
    - ":headphones:"

  # Defaults to False, set status expiration time based upon track length if possible
  set_expiration: False

  # Required fields, defaults to ["artist", "title"]
  required_fields:
    - "artist"
    - "title"

  # Optional track metadata filters
  filters:
    - field: "artist" # choose field to filter, choice of artist, title, album
      partial: "Nickelback" # contents to filter on

  # Optional exceptions, based on track metadata. Takes precedence over required fields and filters
  exceptions:
    - field: "title" # field from TrackInfo: artist, title, album
      partial: "Udemy" # contents to partial match on
      emoji: ":male-student:" # optional custom emoji on matched exception
      message_format: "{title}" # optional custom message format on matched exception

# Optional listener config
listener:
  # Partial match to ignore by player name, check logs to see how player names show up
  # ignore Firefox web based players, where player name is firefox.instanceNNNN
  ignore: ["firefox.instance"]
```

## Configuring Slobbler as a Slack App

1. Add slobbler to [Slack Apps](https://api.slack.com/apps)
2. Click `Create New App`
3. Choose `From scratch`
4. App Name -> `Slobbler` and choose your workspace
5. Click `Create App`
6. Click `Add features and functionality`
7. Choose `Permissions`
8. Click `Add on OAuth Scope` and add `emoji:read`, `users:read`, `users.profile:read`, `users.profile:write`
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

#### Start the service

`systemctl --user enable --now slobbler.service`

#### Monitor logs

`journalctl --user -xeu slobbler.service -f`

## Useful references

- [MPRIS Slack Integration](https://github.com/curtisgibby/mpris-slack-python)
  Good starting place for me, helped with figuring out how to work with DBus/MPRIS. This must be run after a player is playing. Won't handle players exiting or starting.
- [Linux: Spotify Track Notifier](https://muffinresearch.co.uk/linux-spotify-track-notifier-with-added-d-bus-love/)
  Helpful reference when working with DBus/MPRIS. Only works with Spotify and doesn't do anything with Slack
- [dbus-python tutorial](https://dbus.freedesktop.org/doc/dbus-python/tutorial.html)
- [dbus-python examples](https://gitlab.freedesktop.org/dbus/dbus-python/-/tree/master/examples)
