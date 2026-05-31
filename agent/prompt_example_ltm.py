import time
import uuid
import hmac
import hashlib
import base64
import json
import urllib.parse
import requests
import boto3

MemoryClient = None
try:
    from bedrock_agentcore.memory import MemoryClient
except Exception:
    pass


REGION = "eu-west-1"
CLIENT_ID = "1dhubanviv8vkhlq7m05lcshbc"
CLIENT_SECRET = "s06gfqo23jof6i9s7nf7f94mdhek58d8buniu6qnbav4vusqi38"

USER_NAME = "testMemory"
USER_PASSWORD = "MyPassword123!"

AGENT_ARN = "arn:aws:bedrock-agentcore:eu-west-1:923117599216:runtime/blueprint_memory-5gviGIGAUm"
MEMORY_ID = "asa_orchestrator_stm_ltm-dTlZRZ3Bpj"


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
            "USERNAME": username,
            "PASSWORD": password,
            "SECRET_HASH": get_secret_hash(username),
        },
    )
    return resp["AuthenticationResult"]["AccessToken"]


def build_session_id(prefix: str) -> str:
    session_id = f"{prefix}-{int(time.time())}-{uuid.uuid4().hex}"
    if len(session_id) < 33:
        session_id = f"{session_id}-{uuid.uuid4().hex}"
    return session_id


def invoke_agent(prompt: str, actor_id: str, bearer_token: str, session_id: str):
    escaped_arn = urllib.parse.quote(AGENT_ARN, safe="")
    url = (
        f"https://bedrock-agentcore.{REGION}.amazonaws.com"
        f"/runtimes/{escaped_arn}/invocations?qualifier=DEFAULT"
    )
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    payload = {"prompt": prompt, "actor_id": actor_id}
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
    if resp.status_code == 200:
        return resp.json()
    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")


def invoke_agent_without_auth(prompt: str, actor_id: str, session_id: str) -> dict:
    """Invoke agent WITHOUT Authentication header (test inbound auth enforcement)"""
    escaped_arn = urllib.parse.quote(AGENT_ARN, safe="")
    url = (
        f"https://bedrock-agentcore.{REGION}.amazonaws.com"
        f"/runtimes/{escaped_arn}/invocations?qualifier=DEFAULT"
    )
    headers = {
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    payload = {"prompt": prompt, "actor_id": actor_id}
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
    if resp.status_code == 200:
        return resp.json()
    # Expected: 401 Unauthorized if inbound auth is enforced
    return {
        "status": "error",
        "http_code": resp.status_code,
        "message": resp.text,
    }


def retrieve_ltm_hits(actor_id: str, preference_key: str, marker: str):
    if MemoryClient is None:
        return None
    try:
        client = MemoryClient(region_name=REGION)
    except Exception as e:
        print(f"  [retrieve skip] MemoryClient no disponible: {e}")
        return None
    namespaces = [
        f"asa/user/{actor_id}/preferences/",
        f"asa/user/{actor_id}/semantic/",
    ]
    queries = [preference_key, marker, f"{preference_key} {marker}"]
    hits = 0

    for ns in namespaces:
        for query in queries:
            try:
                records = client.retrieve_memories(
                    memory_id=MEMORY_ID,
                    namespace=ns,
                    query=query,
                    top_k=5,
                ) or []
            except Exception as e:
                print(f"  [retrieve skip] Error en retrieve_memories: {e}")
                return None
            for rec in records:
                text = str(rec)
                if preference_key in text and marker in text:
                    hits += 1
    return hits


def test_ltm_unilateral(max_attempts: int = 12, wait_s: int = 30):
    print("\nAutenticando usuario...")
    token = get_bearer_token(USER_NAME, USER_PASSWORD)
    actor_id = USER_NAME
    print(f"  token: {token[:20]}...")

    ts = int(time.time())
    preference_key = f"identificador_ts_{ts}"
    marker = f"id-{uuid.uuid4().hex[:8]}"

    session_seed = build_session_id("ltm-seed")
    session_recall = build_session_id("ltm-recall")

    print(f"  session_seed length: {len(session_seed)}")
    print(f"  session_recall length: {len(session_recall)}")

    print(f"\nSeed session: {session_seed}")
    resp1 = invoke_agent(
        prompt=(
            f"Guarda esta preferencia exacta para futuras sesiones: {preference_key}={marker}. "
            "No la mezcles con otras preferencias y repítela exactamente en tu respuesta."
        ),
        actor_id=actor_id,
        bearer_token=token,
        session_id=session_seed,
    )
    print(f"  Seed response: {resp1}")

    print(f"\nEsperando propagación LTM {wait_s}s...")
    time.sleep(wait_s)

    print(f"\nDEBUG preference_key={preference_key} marker={marker}")
    print(f"\nRecall session: {session_recall}")

    resp2 = None
    recall_ok = False
    for i in range(1, max_attempts + 1):
        resp2 = invoke_agent(
            prompt=(
                f"Cual es el valor de mi preferencia {preference_key} que te di en otra sesión? "
                "Devuelve solo el identificador exacto, sin explicación."
            ),
            actor_id=actor_id,
            bearer_token=token,
            session_id=session_recall,
        )
        recall_ok = marker in str(resp2)
        print(f"  [recall {i}/{max_attempts}] ok={recall_ok}")
        print(f"  Recall response: {resp2}")
        if recall_ok:
            break
        time.sleep(wait_s)

    ltm_hits = None
    for i in range(1, max_attempts + 1):
        ltm_hits = retrieve_ltm_hits(actor_id, preference_key, marker)
        if ltm_hits is None:
            print("  [retrieve skip] MemoryClient no disponible en este entorno")
            break
        print(f"  [retrieve {i}/{max_attempts}] ltm_hits={ltm_hits}")
        if ltm_hits > 0:
            break
        time.sleep(wait_s)

    print("\nCHECK")
    print(f"  recall contains marker : {'PASS' if recall_ok else 'FAIL'}")
    if ltm_hits is None:
        print("  direct retrieve LTM    : SKIP")
    else:
        print(f"  direct retrieve LTM    : {'PASS' if ltm_hits > 0 else 'FAIL'}")

    if recall_ok and (ltm_hits is None or ltm_hits > 0):
        print("\nRESULT: LTM unilateral funcionando correctamente.")
    else:
        print("\nRESULT: ATTENTION — revisar persistencia/recuperación LTM.")

    return {
        "seed": resp1,
        "recall": resp2,
        "preference_key": preference_key,
        "marker": marker,
        "ltm_hits": ltm_hits,
        "recall_ok": recall_ok,
    }


def test_inbound_auth_with_token():
    """Test WITH valid Cognito JWT token"""
    print("\n\n" + "="*70)
    print("TEST: INBOUND AUTH WITH TOKEN (Bearer token)")
    print("="*70)

    try:
        print("\nAuthenticating with Cognito...")
        token = get_bearer_token(USER_NAME, USER_PASSWORD)
        print(f"  ✓ Bearer token obtained: {token[:30]}...")
        
        session_id = build_session_id("test-with-auth")

        print(f"\nInvoking agent WITH Authorization header...")
        prompt = "Dame información de Terraform con deep wiki"
        print(f"  Prompt: {prompt}")
        resp = invoke_agent(
            prompt=prompt,
            actor_id=USER_NAME,
            bearer_token=token,
            session_id=session_id,
        )
        print(f"  ✓ Response received: {str(resp)[:100]}")
        return {"status": "success"}
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return {"status": "error", "error": str(e)}


def test_inbound_auth_without_token():
    """Test WITHOUT authentication header (should fail with 401 if enforced)"""
    print("\n\n" + "="*70)
    print("TEST: INBOUND AUTH WITHOUT TOKEN (No Bearer token)")
    print("="*70)

    print("\nInvoking agent WITHOUT Authorization header...")
    print("  Expected: 401 Unauthorized (if inbound auth is enforced)")

    try:
        ts = int(time.time())
        session_id = build_session_id("test-without-auth")

        prompt = "Dame información de Terraform con deep wiki"
        print(f"  Prompt: {prompt}")
        resp = invoke_agent_without_auth(
            prompt=prompt,
            actor_id=USER_NAME,
            session_id=session_id,
        )
        
        if isinstance(resp, dict) and resp.get("status") == "error":
            http_code = resp.get("http_code")
            if http_code == 401:
                print(f"  ✓ HTTP {http_code}: Authentication enforced (as expected)")
                return {"status": "blocked_auth"}
            else:
                print(f"  ! HTTP {http_code}: Got unexpected HTTP code (expected 401)")
                return {"status": "unexpected", "code": http_code}
        else:
            print(f"  ! Request succeeded without auth (auth not enforced or missing)")
            return {"status": "no_auth_enforced"}
            
    except Exception as e:
        print(f"  ✗ Exception: {e}")
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    test_ltm_unilateral()
    test_inbound_auth_with_token()
    test_inbound_auth_without_token()
