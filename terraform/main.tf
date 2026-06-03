data "aws_caller_identity" "current" {}

data "aws_secretsmanager_secret" "identity_config" {
  count = local.enable_identity ? 1 : 0
  name  = "IDENTITY_CONFIG_COGNITO_AMPLIFY"
}

data "aws_secretsmanager_secret_version" "identity_config" {
  count     = local.enable_identity ? 1 : 0
  secret_id = data.aws_secretsmanager_secret.identity_config[0].id
}

locals {
  config = jsondecode(file("${path.module}/config-tf.json"))
  account_id = data.aws_caller_identity.current.account_id

  # Check if enable/disable Identity in Runtime & Gateway
  enable_identity = try(local.config.enable_identity, true)

  # Check if enable/disable guardrails for Runtime
  # Guardrail is created if guardrails_config section is present in config-tf.json
  guardrails_config = try(local.config.guardrails_config, null)

  # Guardrail configuration values — only read when guardrails_config is present
  guardrails_name                       = local.guardrails_config != null ? try(local.config.guardrails_config.guardrail_name, "") : ""
  guardrails_description                = local.guardrails_config != null ? try(local.config.guardrails_config.guardrail_description, "") : ""
  guardrails_blocked_input_messaging    = local.guardrails_config != null ? try(local.config.guardrails_config.guardrail_blocked_input_message, "Your message was blocked by the content policy.") : "Your message was blocked by the content policy."
  guardrails_blocked_outputs_messaging  = local.guardrails_config != null ? try(local.config.guardrails_config.guardrail_blocked_output_message, "The response was blocked by the content policy.") : "The response was blocked by the content policy."
  guardrails_filter_strength            = local.guardrails_config != null ? try(local.config.guardrails_config.guardrail_filter_strength, "HIGH") : "HIGH"
  guardrails_id_ssm_parameter_name      = local.guardrails_config != null ? try(local.config.guardrails_config.guardrail_id_ssm_parameter_name, "") : ""
  guardrails_version_ssm_parameter_name = local.guardrails_config != null ? try(local.config.guardrails_config.guardrail_version_ssm_parameter_name, "") : ""
  
  # Gateway: use existing if gateway.gateway_id is present, create new otherwise
  gateway_config      = try(local.config.gateway_config, null)
  gateway_existing_id = try(local.config.gateway_config.gateway_id, null)
  gateway_map         = local.gateway_config != null ? { "gw" = local.gateway_config } : {}

  # MCP Targets: only created if mcp_targets section is present
  mcp_target_config = try(local.config.mcp_targets, null)

  # Identity: retrieve discoveryUrl and allowedClients from Secrets Manager (only when enable_identity = true)
  identity_secret          = local.enable_identity ? jsondecode(data.aws_secretsmanager_secret_version.identity_config[0].secret_string) : null
  cognito_client_id        = local.enable_identity ? local.identity_secret["COGNITO_CLIENT_ID"] : null
  cognito_userpool_id      = local.enable_identity ? local.identity_secret["COGNITO_USERPOOL_ID"] : null
  identity_discovery_url   = local.enable_identity ? "https://cognito-idp.eu-west-1.amazonaws.com/${local.cognito_userpool_id}/.well-known/openid-configuration" : ""
  identity_allowed_clients = local.enable_identity ? [local.cognito_client_id] : null

  gateway_identity_authorizer_configuration = local.enable_identity ? {
    customJWTAuthorizer = {
      discoveryUrl   = local.identity_discovery_url
      allowedClients = local.identity_allowed_clients
    }
  } : null
}

module "agentcore_runtime" {
  source = "git::https://github.com/EdrochaA/runtime-module.git?ref=develop"

  aws_region                  = local.config.runtime_deployment.region
  ecr_image_uri               = var.ecr_image_uri
  agentcore_runtime_role_name = "${local.config.runtime_deployment.agent_name}-role"
  agentcore_name              = local.config.runtime_deployment.agent_name
  jwt_discovery_url           = local.identity_discovery_url
  jwt_allowed_clients         = local.identity_allowed_clients
  request_header_allowlist    = local.enable_identity ? try(local.config.runtime_deployment.identity_config.request_header_configuration.requestHeaderAllowlist, []) : []

  # Guardrail — only created when guardrails_config is present in config-tf.json
  guardrail_name                        = local.guardrails_name
  guardrail_description                 = local.guardrails_description
  guardrail_blocked_input_message       = local.guardrails_blocked_input_messaging
  guardrail_blocked_output_message      = local.guardrails_blocked_outputs_messaging
  guardrail_filter_strength             = local.guardrails_filter_strength
  guardrail_id_ssm_parameter_name       = local.guardrails_id_ssm_parameter_name
  guardrail_version_ssm_parameter_name  = local.guardrails_version_ssm_parameter_name
}

module "agentcore_gateway" {
  for_each = local.gateway_map

  source = "git::https://github.com/EdrochaA/gateway-module.git?ref=develop"

  aws_region                 = local.config.runtime_deployment.region
  agentcore_gateway_name     = try(each.value.name, null)
  existing_gateway_id        = local.gateway_existing_id
  authorizer_type            = try(each.value.authorizer_type, "NONE")
  description                = try(each.value.description, "")
  role_name                  = "${each.value.name}-role"
  authorizer_configuration   = try(each.value.authorizer_type, null) == "CUSTOM_JWT" ? local.gateway_identity_authorizer_configuration : null
  mcp_target_config          = local.mcp_target_config
  gateway_ssm_parameter_name = each.value.ssm_parameter_name
}