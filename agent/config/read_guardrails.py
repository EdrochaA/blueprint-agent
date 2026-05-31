import json
import logging
import boto3
from .guardrails_dto import GuardrailsConfigDTO

logger = logging.getLogger("blueprint-agent-memory")


def _get_ssm_parameter(param_name: str, region: str) -> str:
    """Fetch a string value from AWS SSM Parameter Store.

    Args:
        param_name: Name/path of the SSM parameter.
        region: AWS region where the parameter is stored.

    Returns:
        The parameter value as a string.

    Raises:
        ValueError: If the parameter is not found.
        RuntimeError: On any other SSM error.
    """
    ssm_client = boto3.client("ssm", region_name=region)
    try:
        response = ssm_client.get_parameter(Name=param_name)
        return response["Parameter"]["Value"].strip()
    except ssm_client.exceptions.ParameterNotFound:
        raise ValueError(f"SSM parameter '{param_name}' not found in region '{region}'.")
    except Exception as e:
        raise RuntimeError(f"Error fetching SSM parameter '{param_name}': {e}") from e


def is_guardrails_enabled(config_path: str = "agent/config/guardrails.json") -> bool:
    """Return True if guardrails.json has non-empty SSM parameter names.

    Args:
        config_path: Path to the guardrails.json file.

    Returns:
        True if both SSM parameter names are set, False otherwise.
    """
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        guardrails = data.get("guardrails", {})
        return bool(
            guardrails.get("guardrail_id_ssm_parameter_name")
            and guardrails.get("guardrail_version_ssm_parameter_name")
        )
    except Exception:
        return False


def read_guardrails(
    config_path: str = "agent/config/guardrails.json",
    region: str = "eu-west-1",
) -> GuardrailsConfigDTO:
    """Read guardrails.json and return a GuardrailsConfigDTO object.

    Resolution logic for guardrail_id and guardrail_version:
    - If guardrail_id_ssm_parameter_name and guardrail_version_ssm_parameter_name
      are set in guardrails.json, the values are fetched from SSM Parameter Store.
      This covers both:
        * A guardrail created by Terraform via guardrails_config in config-tf.json
          (Terraform writes the SSM parameters automatically).
        * An existing guardrail from another repo (SSM paths set manually).
    - If neither SSM path is set, guardrail_id and guardrail_version are read
      directly from guardrails.json (fallback for local testing only).
    - If no guardrail configuration is present at all, all guardrail fields
      are None and the agent runs without guardrails.

    Args:
        config_path: Path to the guardrails.json file.
        region: AWS region used to resolve SSM parameters.

    Returns:
        GuardrailsConfigDTO with all guardrail settings populated.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    guardrails = data.get("guardrails", {})

    # Resolve guardrail_id
    guardrail_id_ssm = guardrails.get("guardrail_id_ssm_parameter_name") or None
    if guardrail_id_ssm:
        logger.info(f"Resolving guardrail_id from SSM: {guardrail_id_ssm}")
        guardrail_id = _get_ssm_parameter(guardrail_id_ssm, region)
    else:
        guardrail_id = guardrails.get("guardrail_id") or None
        if guardrail_id:
            logger.info("Using hardcoded guardrail_id from guardrails.json")
        else:
            logger.info("No guardrail_id configured — guardrails disabled")

    # Resolve guardrail_version
    guardrail_version_ssm = guardrails.get("guardrail_version_ssm_parameter_name") or None
    if guardrail_version_ssm:
        logger.info(f"Resolving guardrail_version from SSM: {guardrail_version_ssm}")
        guardrail_version = _get_ssm_parameter(guardrail_version_ssm, region)
    else:
        guardrail_version = guardrails.get("guardrail_version") or None

    return GuardrailsConfigDTO(
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        guardrail_trace=guardrails.get("guardrail_trace"),
        guardrail_stream_processing_mode=guardrails.get("guardrail_stream_processing_mode"),
        guardrail_redact_input=guardrails.get("guardrail_redact_input"),
        guardrail_redact_input_message=guardrails.get("guardrail_redact_input_message"),
        guardrail_redact_output=guardrails.get("guardrail_redact_output"),
        guardrail_redact_output_message=guardrails.get("guardrail_redact_output_message"),
        guardrail_latest_message=guardrails.get("guardrail_latest_message"),
    )
