
# Now Playing to Slack Status
Updates slack status based upon any media player using the [MPRIS DBus Protocol](https://specifications.freedesktop.org/mpris-spec/latest/)

Create a config file with the following

```yaml
user_id: U1232 # user id from slack
user_oauth_token: xoxp-token # oath token from your slack app configuration
playing_emoji: ":notes:" # emoji to use when playing music
```

### Running
`./now-playing now-playing.yaml`

### systemd
```
[Unit]
Description=Now playing to slack status
After=network.target

[Service]
ExecStart=now-playing --config ~/.config/now-playing-slack.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```
`systemctl --user enable now-playing.service`

# Useful source references

https://github.com/curtisgibby/mpris-slack-python/blob/master/mpris-track-change-to-slack.py
https://dbus.freedesktop.org/doc/dbus-python/tutorial.html#signal-matching
https://gitlab.freedesktop.org/dbus/dbus-python/-/blob/master/examples/example-async-client.py
https://muffinresearch.co.uk/linux-spotify-track-notifier-with-added-d-bus-love/
https://github.com/altdesktop/playerctl/blob/master/examples/basic-example.py