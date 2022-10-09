#!/usr/bin/env python

import argparse
import logging
import os

from listener import MPRISListener
from scrobble import SlackStatus

logging.basicConfig(level=logging.INFO)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        help="YAML configuration file",
        required=False,
        default="config.yaml",
    )
    args = parser.parse_args()

    slack = SlackStatus(os.path.expanduser(args.config))
    listener = MPRISListener(slack.handle_track_update, slack.handle_stop_playing)
    listener.run_loop()


if __name__ == "__main__":
    main()
