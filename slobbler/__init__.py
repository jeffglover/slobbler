__all__ = ["cli", "MPRISListener", "SlackStatus", "SlackAPI", "Slobble", "NoScrobble"]

import argparse
import logging
import os
from pprint import pformat
from typing import Any, Dict

from yaml import safe_load as load

from .listener import MPRISListener
from .slobble import SlackAPI, Slobble, NoScrobble


def cli():
    no_scrobble, slack_config, slobbler_config, listener_config = setup()

    if no_scrobble:
        slobble = NoScrobble()
    else:
        slobble = Slobble(SlackAPI(slack_config), slobbler_config)

    listener = MPRISListener(
        listener_config, slobble.handle_track_update, slobble.handle_stop_playing
    )
    listener.run_loop()


def setup() -> tuple[bool, Dict[str, str], Dict[str, Any], Dict[str, Any]]:
    args = setup_parser().parse_args()
    config = read_config_file(os.path.expanduser(args.config))

    no_scrobble = config.get("no_scrobble", False)
    verbose = config.get("verbose", False)

    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    logger = logging.getLogger("main")
    logger.debug(pformat(config, indent=True))

    return no_scrobble, config["slack"], config["slobbler"], config.get("listener", {})


def setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config",
        help="YAML configuration file",
        required=False,
        default="config.yaml",
    )
    return parser


def read_config_file(config_file: str) -> Dict[str, Any]:
    assert os.path.isfile(config_file), f"not a file: {config_file}"
    with open(config_file, "r") as fh:
        return load(fh)
