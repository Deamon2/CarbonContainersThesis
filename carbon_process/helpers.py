import json
import logging
import os
from typing import Any

import yaml

logger = logging.getLogger("helpers")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "flag_config.yaml")


def load_flag_config():
    if not os.path.exists(CONFIG_PATH):
        logger.warning("[helpers] Flag config not found at %s", CONFIG_PATH)
        return {}

    try:
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning("[helpers] Could not read flag config %s: %s", CONFIG_PATH, exc)
        return {}


def read_flags_json(filepath: str):
    if not os.path.exists(filepath):
        logger.warning("[helpers] Flags file not found: %s", filepath)
        return None

    try:
        with open(filepath, "r") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("[helpers] Could not read %s: %s", filepath, exc)
        return None

    if not isinstance(data, dict):
        logger.warning("[helpers] Invalid flags file structure in %s", filepath)
        return None

    return data
