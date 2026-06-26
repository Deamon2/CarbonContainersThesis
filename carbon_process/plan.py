import logging
from typing import Any

from temporalio import activity

from carbon_process.helpers import load_flag_config, read_flags_json
from carbon_process.model import AnalysisResult

logger = logging.getLogger("plan")


def target_index(action: str, current_idx: int, levels: list[Any]):
    if action == "degrade" and current_idx < len(levels) - 1:
        return current_idx + 1
    if action == "upgrade" and current_idx > 0:
        return current_idx - 1
    return None


@activity.defn
async def plan(analysis: AnalysisResult):
    if analysis.action not in {"degrade", "upgrade"}:
        logger.warning("Unsupported action: %s", analysis.action)
        return None, None, None, None

    flag_config = load_flag_config()
    containers = flag_config.get("containers", {})
    if not isinstance(containers, dict):
        logger.warning("Invalid flag config: missing containers mapping")
        return None, None, None, None

    for container_name in analysis.candidates:

        container_config = containers.get(container_name)
        if not isinstance(container_config, dict):
            logger.info("Candidate %s not found in flag config", container_name)
            continue

        filepath = container_config.get("filepath")
        flags = container_config.get("flags", [])
        if not filepath or not isinstance(flags, list):
            logger.warning("Invalid flag config for container %s", container_name)
            continue

        flags_json = read_flags_json(filepath)
        if flags_json is None:
            continue

        flags_json_data = flags_json.get("flags")
        if not isinstance(flags_json_data, dict):
            logger.warning("Invalid flags.json structure in %s", filepath)
            continue

        valid_flags = []
        current_flag_level = 0
        max_flag_level = 0
        target_flag_name = None
        target_flag_state = None
        degradation_status = None
        current_degradation_status = None

        for flag in flags:
            if not isinstance(flag, dict):
                continue

            flag_name = flag.get("name")
            levels = flag.get("levels", [])
            if not flag_name or not isinstance(levels, list) or not levels:
                logger.warning("Invalid flag entry for container %s", container_name)
                continue

            flag_obj = flags_json_data[flag_name]
            current_state = flag_obj["defaultVariant"]
            if current_state not in levels:
                logger.info("Flag %s in %s has no matching defaultVariant", flag_name, filepath)
                continue

            current_idx = levels.index(current_state)
            current_flag_level += current_idx
            if len(levels) > 1:
                max_flag_level += len(levels) - 1

            valid_flags.append((flag_name, levels, current_idx))

        ordered_flags = valid_flags if analysis.action == "degrade" else list(reversed(valid_flags))

        for flag_name, levels, current_idx in ordered_flags:
            if len(levels) < 2 or target_flag_name is not None:
                continue

            next_idx = target_index(analysis.action, current_idx, levels)
            if next_idx is None:
                continue

            target_flag_name = flag_name
            target_flag_state = levels[next_idx]
            logger.info(
                "%s %s.%s: %s -> %s (reason: %s)",
                analysis.action,
                container_name,
                flag_name,
                levels[current_idx],
                target_flag_state,
                analysis.reason,
            )

            degradation_status = 0 if max_flag_level == 0 else (current_flag_level - current_idx + next_idx) / max_flag_level

        if target_flag_name is not None:
            return container_name, target_flag_name, target_flag_state, degradation_status
        else:
            try:
                from carbon_process.metrics_server import metrics
                current_degradation_status = 0 if max_flag_level == 0 else current_flag_level / max_flag_level
                metrics.update_degradation_status(container_name=container_name, degradation_status=current_degradation_status)
            except Exception:
                logger.debug("Prometheus metrics update failed")


    logger.info("No executable flag action found for %s candidates: %s", analysis.action, analysis.candidates)
    return None, None, None, None
