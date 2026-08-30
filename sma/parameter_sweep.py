from itertools import product
from typing import Any

SPECIAL_SECTIONS = ("carbon_workflow", "system")


def param_combinations(parameters: dict[str, list[Any]]):
    if not parameters:
        return [{}]

    names = list(parameters.keys())
    value_lists = [parameters[name] for name in names]
    return [dict(zip(names, combo)) for combo in product(*value_lists)]


def build_sim_configs(parameter_config: dict[str, dict[str, list[Any]]]):
    system_options = parameter_config["system"]["test_systems"]

    common_sections = {
        section: parameters
        for section, parameters in parameter_config.items()
        if section not in SPECIAL_SECTIONS
    }
    common_section_names = list(common_sections.keys())
    common_combos_per_section = [
        param_combinations(common_sections[section]) for section in common_section_names
    ]

    carbon_combos = param_combinations(parameter_config.get("carbon_workflow", {}))

    for common_combo in product(*common_combos_per_section):
        common_sim_config = dict(zip(common_section_names, common_combo))

        for system in system_options:
            sim_config = {**common_sim_config, "system": {"test_systems": system}}

            if system == "combined":
                for carbon_combo in carbon_combos:
                    yield {**sim_config, "carbon_workflow": carbon_combo}
            else:
                yield sim_config
