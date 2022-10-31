__all__ = ["cli", "MPRISListener", "Slobble", "DryRun"]

import argparse
import logging
import os
from pprint import pformat
from typing import Any, Dict

from yaml import safe_load as load

from .listener import MPRISListener
from .slobble import Slobble, DryRun


def cli():
    dry_run, config = setup()

    if dry_run:
        slobble = DryRun()
    else:
        slobble = Slobble(config)

    listener = MPRISListener(slobble.handle_track_update, slobble.handle_stop_playing)
    listener.run_loop()


def setup() -> tuple[bool, Dict[str, Any]]:
    args = setup_parser().parse_args()
    config = read_config_file(os.path.expanduser(args.config))

    dry_run = config.get("dry_run", False)
    verbose = config.get("verbose", False)
    slobbler_config = parse_slobbler_config(config["slobbler"])

    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    logger = logging.getLogger("main")
    logger.debug(pformat(config, indent=True))

    return dry_run, slobbler_config


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


def parse_slobbler_config(config: Dict[str, Any]) -> Dict[str, Any]:
    parsed_config = {
        "token": config["user_oauth_token"],
        "user_id": config["user_id"],
        "playing_emoji": config["playing_emoji"],
    }
    parsed_config["fallback_emojis"] = parsed_config["playing_emoji"][
        "fallback"
    ]  # must have at least one
    parsed_config["valid_playing_emojis"] = [
        "",  # empty "playing" emoji is valid
        *parsed_config["fallback_emojis"],
    ]

    # add player specific emojis
    parsed_config["valid_playing_emojis"].extend(
        (
            emoji
            for player, emoji in parsed_config["playing_emoji"].items()
            if player != "fallback"
        )
    )
    return parsed_config
