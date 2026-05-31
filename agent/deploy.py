import os
import sys
import json
from bedrock_agentcore_starter_toolkit import Runtime


def read_deployment_config(project_root):
    """Load deployment configuration from config-tf.json file.

    Args:
        project_root (str): Path to the project root directory

    Returns:
        dict: Deployment configuration dictionary
    """
    config_path = os.path.join(project_root, "config-tf.json")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
            deployment_config = config.get("runtime_deployment", {})
            print(f"Configuration loaded from: {config_path}")
            return deployment_config
    except FileNotFoundError:
        print(f"Warning: config.json not found at {config_path}. Using default values.")
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing config.json: {e}. Using default values.")
        return {}

def deploy():
    # Change working directory to project root to ensure relative paths work correctly during deployment
    current_script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_script_dir)
    os.chdir(project_root)

    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Load configuration from config-tf.json
    deployment_config = read_deployment_config(project_root)

    # Clean up old configuration file if it exists to avoid conflicts with new deployment settings
    config_file = ".bedrock_agentcore.yaml"
    if os.path.exists(config_file):
        os.remove(config_file)
        print(f"Cleaning up old configuration: {config_file}")

    # Define deployment parameters with config-tf.json
    agent_name = deployment_config.get("agent_name", "runtime_memory_v1")
    entrypoint = deployment_config.get("entrypoint", "agent/main.py")  # Path relative to project root
    auto_create_execution_role = deployment_config.get("auto_create_execution_role", True)
    auto_create_ecr = deployment_config.get("auto_create_ecr", True)
    requirements_file = deployment_config.get("requirements_file", "requirements.txt")  # Must be located in the root
    region = deployment_config.get("region", "eu-west-1")
    memory_mode = deployment_config.get("memory_mode", "NO_MEMORY")
    identity_config = deployment_config.get("identity_config")
    request_header_configuration = identity_config.get("request_header_configuration")
    authorizer_configuration = identity_config.get("authorizer_configuration")
    auto_update_on_conflict = deployment_config.get("auto_update_on_conflict", True)

    print(f"Starting deployment in: {region}...")
    print(f"Agent name: {agent_name}")

    runtime = Runtime()

    try:
        # Configure the agentcore runtime with the specified parameters
        runtime.configure(
            entrypoint=entrypoint,
            agent_name=agent_name,
            requirements_file=requirements_file,
            region=region,
            auto_create_execution_role=auto_create_execution_role,
            auto_create_ecr=auto_create_ecr,
            # Memory is managed manually via the MemorySession SDK inside the agent.
            # AgentCore built-in memory is therefore disabled here.
            memory_mode=memory_mode,
            # Inbound authorization: only users with a valid Cognito JWT can invoke.
            request_header_configuration=request_header_configuration,
            authorizer_configuration=authorizer_configuration,
        )

        # Launch the deployment and print the resulting Agent ARN
        result = runtime.launch(
            auto_update_on_conflict=auto_update_on_conflict,
        )

        print(f"\nDeployment Successful!")
        print(f"Agent ARN: {result.agent_arn}")

    except Exception as e:
        print(f"\nDeployment Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    deploy()
