from dataclasses import dataclass
from typing import Optional


@dataclass
class PromptManagementConfigDTO:
    """Configuration for prompt management.

    The active section (key 'prompt_management' in prompt_management.json) is read
    by read_prompt_management(). The mode is derived from the fields present:
    - 'system_prompt_path' set  → file-based: reads the prompt from a local .txt file.
    - Otherwise                 → Bedrock + SSM: fetches the prompt from Bedrock Prompt Management

    Attributes:
        region: AWS region where the Bedrock prompt is stored
        prompt_id: ARN of the prompt in Bedrock
	    param_name_version: Name of the SSM parameter that holds the current prompt version
        system_prompt_path: Path to the .txt file containing the system prompt
    """
    region: Optional[str]
    prompt_id: Optional[str]
    param_name_version: Optional[str]
    system_prompt_path: Optional[str]