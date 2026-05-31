
#STM Test


import time
import hmac
import hashlib
import base64
import json
import urllib.parse
import requests
import boto3


#config
REGION        = "eu-west-1"
COGNITO_POOL  = "eu-west-1_krL5ewLFS"
CLIENT_ID     = "1dhubanviv8vkhlq7m05lcshbc"
CLIENT_SECRET = "s06gfqo23jof6i9s7nf7f94mdhek58d8buniu6qnbav4vusqi38"


USER1_NAME     = "testMemory"
USER1_PASSWORD = "MyPassword123!"
USER2_NAME     = "testMemory2"
USER2_PASSWORD = "MyPassword123!"


AGENT_ARN = "arn:aws:bedrock-agentcore:eu-west-1:923117599216:runtime/blueprint_memory-5gviGIGAUm"


def get_secret_hash(username: str) -> str:
    message = username + CLIENT_ID
    dig = hmac.new(
        key=CLIENT_SECRET.encode("utf-8"),
        msg=message.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(dig).decode()


def get_bearer_token(username: str, password: str) -> str:
    cognito = boto3.client("cognito-idp", region_name=REGION)
    resp = cognito.initiate_auth(
        ClientId=CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME":    username,
            "PASSWORD":    password,
            "SECRET_HASH": get_secret_hash(username),
        },
    )
    return resp["AuthenticationResult"]["AccessToken"]


def invoke_agent(
    prompt: str,
    actor_id: str,
    bearer_token: str,
    session_id: str,
) -> str:

    escaped_arn = urllib.parse.quote(AGENT_ARN, safe="")
    url = (
        f"https://bedrock-agentcore.{REGION}.amazonaws.com"
        f"/runtimes/{escaped_arn}/invocations?qualifier=DEFAULT"
    )
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type":  "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    #actor_id is sent in the payload
    payload = {
        "prompt": prompt,
        "actor_id": actor_id,
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
    if resp.status_code == 200:
        return resp.json()
    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")


#STM  test


def test_user_memory_isolation():

    #Auth
    print("\nAuthenticating users...")
    token_user1 = get_bearer_token(USER1_NAME, USER1_PASSWORD)
    token_user2 = get_bearer_token(USER2_NAME, USER2_PASSWORD)
    print(f"  user1 token: {token_user1[:20]}...")
    print(f"  user2 token: {token_user2[:20]}...")


    ts = int(time.time())
    session_user1 = f"agent-session-identity-test-1234567890-{ts}"
    session_user2 = f"agent-session-identity-test-1234567890__V2-{ts}"


    #testuser1 asks about devices of a specific household(getEvDevices)

    print("\nuser1 → asking about devices of TEST-EV-OPTIMIZATION-5...")
    resp1 = invoke_agent(
        prompt="Que dispositivos tiene el household TEST-EV-OPTIMIZATION-5?",
        actor_id=USER1_NAME,
        bearer_token=token_user1,
        session_id=session_user1,
    )
    print(f"  Response: {resp1}")


    #testuser2 asks about a different household

    print("\nuser2 → asking about TEST-EV-OPTIMIZATION-7 notifications...")
    resp2 = invoke_agent(
        prompt="Tiene notificaciones activadas TEST-EV-OPTIMIZATION-7?",
        actor_id=USER2_NAME,
        bearer_token=token_user2,
        session_id=session_user2,
    )
    print(f"  Response: {resp2}")

    #testuser1 asks what household was previously discussed

    print("\nuser1 → 'Cual es el household/usuario que te pregunte?'")
    resp3 = invoke_agent(
        prompt="Cual es el household/usuario que te pregunte?",
        actor_id=USER1_NAME,
        bearer_token=token_user1,
        session_id=session_user1,
    )
    print(f"  Response: {resp3}")


    #testuser2 asks the same question in their own session

    print("\nuser2 → 'Cual es el household/usuario que te pregunte?'")
    resp4 = invoke_agent(
        prompt="Cual es el household/usuario que te pregunte?",
        actor_id=USER2_NAME,
        bearer_token=token_user2,
        session_id=session_user2,
    )
    print(f"  Response: {resp4}")


    # solation verdict


    print("CHECK")

    user1_correct = "TEST-EV-OPTIMIZATION-5" in str(resp3)
    user2_correct = "TEST-EV-OPTIMIZATION-7" in str(resp4)

    print(f"  user1 recalled correct household : {'PASS' if user1_correct else 'FAIL'}")
    print(f"  user2 recalled correct household : {'PASS' if user2_correct else 'FAIL'}")

    if user1_correct and user2_correct:
        print("\nRESULT: STM isolation is working correctly.")
    else:
        print("\nRESULT: ATTENTION — memory isolation may not be working as expected.")

    return {
        "step1": resp1,
        "step2": resp2,
        "step3_user1_recall": resp3,
        "step4_user2_recall": resp4,
    }


if __name__ == "__main__":
    test_user_memory_isolation()
