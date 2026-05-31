# -----------------------------------------------------------------------
# Outputs — Guardrail identifiers from the runtime module
#
# These values can be used to populate agent/config/guardrails.json
# or written to SSM Parameter Store for runtime consumption.
# -----------------------------------------------------------------------

output "guardrail_id" {
  description = "ID of the Bedrock Guardrail created by the runtime module. Null if guardrails are disabled."
  value       = module.agentcore_runtime.guardrail_id
}

output "guardrail_version" {
  description = "Published version number of the Guardrail. Null if guardrails are disabled."
  value       = module.agentcore_runtime.guardrail_version
}

output "guardrail_arn" {
  description = "ARN of the Bedrock Guardrail. Null if guardrails are disabled."
  value       = module.agentcore_runtime.guardrail_arn
}
