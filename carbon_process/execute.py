import logging
import os
import json
import tempfile
from temporalio import activity

from carbon_process.helpers import load_flag_config, read_flags_json

logger = logging.getLogger("execute")


def write_flags_json(filepath, data):
    parent = os.path.dirname(filepath) or "."
    os.makedirs(parent, exist_ok=True)
    
    fd, tmp_path = tempfile.mkstemp(prefix="flags_", suffix=".json", dir=parent)
    try:
        with os.fdopen(fd, "w") as tmp:
            json.dump(data, tmp, indent=4)
        os.replace(tmp_path, filepath)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        logger.error(f"Could not write {filepath}: {e}")
        raise


def set_flag_state(container_name: str, flag_name: str, flag_state: str):
    config = load_flag_config()
    containers = config.get("containers", {})
    
    if container_name not in containers:
        logger.error(f"Container '{container_name}' not found in config")
        return False
    
    container_config = containers[container_name]
    filepath = container_config.get("filepath")
    flags = container_config.get("flags", [])
    
    if not filepath:
        logger.error(f"No filepath configured for container '{container_name}'")
        return False
    
    flag_config = None
    for flag in flags:
        if flag.get("name") == flag_name:
            flag_config = flag
            break
    
    if not flag_config:
        logger.error(f"Flag '{flag_name}' not found for container '{container_name}'")
        return False
    
    levels = flag_config.get("levels", [])
    if flag_state not in levels:
        logger.error(f"Invalid flag_state '{flag_state}'")
        return False
    
    flags_json = read_flags_json(filepath)
    if flags_json is None:
        return False
    
    if "flags" not in flags_json:
        logger.error(f"Invalid flags.json structure")
        return False
    
    if flag_name not in flags_json["flags"]:
        logger.error(f"Flag '{flag_name}' not found in {filepath}")
        return False
    
    flags_json["flags"][flag_name]["defaultVariant"] = flag_state
    
    try:
        write_flags_json(filepath, flags_json)
        return True
    except Exception as e:
        logger.error(f"Failed to set flag state: {e}")
        return False


@activity.defn
async def execute(container_name: str, flag_name: str, flag_state: str, degradation_status: float):
    from carbon_process.metrics_server import metrics

    success = set_flag_state(container_name, flag_name, flag_state)
    if success:
        logger.info(f"Successfully applied decision: {container_name}, {flag_name}, {flag_state}. Degradation status: {degradation_status:.2f}")
        try:
            metrics.update_degradation_status(container_name=container_name, degradation_status=degradation_status)
        except Exception:
            logger.debug("Prometheus metrics update failed")

        return True
    
    logger.warning(f"Failed to apply decision: {container_name}, {flag_name}, {flag_state}")
    return False
