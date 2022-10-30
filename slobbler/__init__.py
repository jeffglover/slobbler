__all__ = ["cli", "MPRISListener", "Slobble"]

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
    dry_run, verbose, config = parse_config_file(os.path.expanduser(args.config))

    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    logger = logging.getLogger("main")
    logger.debug(pformat(config, indent=True))

    return dry_run, config


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


def parse_config_file(config_file: str) -> tuple[bool, bool, Dict[str, Any]]:
    assert os.path.isfile(config_file), f"not a file: {config_file}"
    with open(config_file, "r") as fh:
        config = load(fh)

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
    return config.get("dry_run", False), config.get("verbose", False), parsed_config