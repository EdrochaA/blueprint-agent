from dataclasses import dataclass


@dataclass
class GuardrailsConfigDTO:
    """Guardrails configuration for BedrockModel.

    guardrail_id and guardrail_version are resolved at load time from
    SSM Parameter Store using the ssm parameter names defined in guardrails.json.
    """
    guardrail_id: str | None = None
    guardrail_version: str | None = None
    guardrail_trace: str | None = None
    guardrail_stream_processing_mode: str | None = None
    guardrail_redact_input: bool | None = None
    guardrail_redact_input_message: str | None = None
    guardrail_redact_output: bool | None = None
    guardrail_redact_output_message: str | None = None
    guardrail_latest_message: bool | None = None
