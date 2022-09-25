# slobbler

Slack status scrobbler. Updates slack status based upon any media player using the [MPRIS DBus Protocol](https://specifications.freedesktop.org/mpris-spec/latest/)

# Features

- Connects to all players, publishes only the playing one
- Clears status on pause or player exit
- Filters when track is missing artist info, likely a video on a webpage

### Configuration

Create a config file with the following

```yaml
user_id: U123456 # user id from slack
user_oauth_token: xoxp-token # oath token from your slack app configuration
playing_emoji: ":notes:" # emoji to use when playing music
```

### Running

`./slobbler.py config.yaml`

### systemd

```
[Unit]
Description=Slack status scrobbler
After=network.target

[Service]
ExecStart=slobbler.py --config ~/.config/slobbler.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

`systemctl --user enable --now slobbler.service`

# TODOs

- Make this a Python package
- Better and configurable filtering
    * Track/Artist name
    * Player name
    * If it's a browser, can I tell what website it's on?

# Useful references

https://github.com/curtisgibby/mpris-slack-python/blob/master/mpris-track-change-to-slack.py
https://dbus.freedesktop.org/doc/dbus-python/tutorial.html#signal-matching
https://gitlab.freedesktop.org/dbus/dbus-python/-/blob/master/examples/example-async-client.py
https://muffinresearch.co.uk/linux-spotify-track-notifier-with-added-d-bus-love/
https://github.com/altdesktop/playerctl/blob/master/examples/basic-example.py