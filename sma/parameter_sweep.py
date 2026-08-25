from typing import Any


def build_sim_config(parameter_config: dict[str, dict[str, list[Any]]]):
    """Build a simulation config by selecting the first option per parameter."""
    sim_config: dict[str, dict[str, Any]] = {}
    for section, parameters in parameter_config.items():

        sim_config[section] = {}
        for parameter, options in parameters.items():
            sim_config[section][parameter] = options[0]

    return sim_config

# muss an neues yaml format angepasst werden
