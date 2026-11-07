from itertools import product

SCENARIO_SECTIONS = ("load_shape", "ci_scenario")
SYSTEM_PARAMETER_SECTIONS = {"combined": ("carbon_coordinator",)}


def section_combinations(parameter_config, section_names):
    # gib alle Kombinationen für die Konfigurationen zurück
    combinations_per_section = [
        [
            {
                parameter: values[index]
                for index, parameter in enumerate(parameters)
            }
            for values in product(*parameter_config[section].values())
        ]
        for section in section_names
        for parameters in [parameter_config[section]]
    ]

    return [
        {
            section: values[index]
            for index, section in enumerate(section_names)
        }
        for values in product(*combinations_per_section)
    ]


def build_sim_configs(parameter_config):
    scenario_configs = section_combinations(parameter_config, SCENARIO_SECTIONS)
    systems = parameter_config["system"]["test_systems"]
    sim_configs = []

    for scenario_config in scenario_configs:
        for system in systems:
            parameter_sections = SYSTEM_PARAMETER_SECTIONS.get(system, ())

            for system_parameters in section_combinations(parameter_config,parameter_sections):
                sim_config = dict(scenario_config)
                sim_config["system"] = {"test_systems": system}
                sim_config.update(system_parameters)
                sim_configs.append(sim_config)

    return sim_configs
