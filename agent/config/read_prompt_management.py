import json
from .prompt_management_dto import PromptManagementConfigDTO


def read_prompt_management(config_path: str = "agent/config/prompt_management.json") -> PromptManagementConfigDTO:
    """Read prompt_management.json and return a PromptManagementConfigDTO object.

    The file contains two sections: 'prompt_management' (active) and
    'prompt_management_disabled' (inactive). To switch sources, rename the keys manually.
 
    The mode is derived automatically from the fields present in the active section:
        - 'system_prompt_path' present -> file-based mode (reads from .txt file)
        - Otherwise                    -> Bed
    Args:
        config_path: Path to the prompt_management.json file.

    Returns:
        PromptManagementConfigDTO with the active configuration.
 
    Raises:
        ValueError: If no 'prompt_management' key is found in the file.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    active = data.get("prompt_management")
    if active is None:
        raise ValueError(
            "No active 'prompt_management' key found in prompt_management.json. "
            "Rename 'prompt_management_disabled' to 'prompt_management' to activate a source."
        )
 
    if "system_prompt_path" in active:
        return PromptManagementConfigDTO(
            region=None,
            prompt_id=None,
            param_name_version=None,
            system_prompt_path=active.get("system_prompt_path"),
        )

    return PromptManagementConfigDTO(
        region=active.get("region"),
        prompt_id=active.get("prompt_id"),
        param_name_version=active.get("param_name_version"),
        system_prompt_path=None,
    )
