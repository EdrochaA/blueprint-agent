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


def test_stm_ltm_unilateral(max_attempts: int = 12, wait_s: int = 20):
    print("\nAutenticando usuario...")
    token = get_bearer_token(USER_NAME, USER_PASSWORD)
    actor_id = USER_NAME
    print(f"  token: {token[:20]}...")

    ts = int(time.time())
    preference_key = f"identificador_ts_{ts}"
    marker = f"id-{uuid.uuid4().hex[:8]}"
    household = "TEST-EV-OPTIMIZATION-5"

    session_a = build_session_id("seed-session-a")
    session_b = build_session_id("work-session-b")

    print(f"  session_a length: {len(session_a)}")
    print(f"  session_b length: {len(session_b)}")

    print(f"\nSesion A (seed LTM): {session_a}")
    resp1 = invoke_agent(
        prompt=(
            f"Guarda esta preferencia exacta para futuras sesiones: {preference_key}={marker}. "
            "No la mezcles con otras preferencias y repítela exactamente ahora."
        ),
        actor_id=actor_id,
        bearer_token=token,
        session_id=session_a,
    )
    print(f"  Seed response: {resp1}")

    print(f"\nSesion B (STM): {session_b}")
    resp2 = invoke_agent(
        prompt=f"Que dispositivos tiene el household {household}?",
        actor_id=actor_id,
        bearer_token=token,
        session_id=session_b,
    )
    print(f"  STM question response: {resp2}")

    resp3 = invoke_agent(
        prompt="Cual es el household que te acabo de preguntar en esta sesión?",
        actor_id=actor_id,
        bearer_token=token,
        session_id=session_b,
    )
    print(f"  STM recall response: {resp3}")

    stm_ok = household in str(resp3)

    print(f"\nEsperando propagación LTM {wait_s}s...")
    time.sleep(wait_s)

    print(f"\nDEBUG preference_key={preference_key} marker={marker}")

    resp4 = None
    ltm_ok = False
    for i in range(1, max_attempts + 1):
        resp4 = invoke_agent(
            prompt=(
                f"Dime el valor de mi preferencia {preference_key} que te compartí en otra sesión. "
                "Devuelve solo el identificador exacto, sin explicación."
            ),
            actor_id=actor_id,
            bearer_token=token,
            session_id=session_b,
        )
        ltm_ok = marker in str(resp4)
        print(f"  [ltm recall {i}/{max_attempts}] ok={ltm_ok}")
        print(f"  LTM recall response: {resp4}")
        if ltm_ok:
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
    print(f"  stm recall household : {'PASS' if stm_ok else 'FAIL'}")
    print(f"  ltm recall marker    : {'PASS' if ltm_ok else 'FAIL'}")
    if ltm_hits is None:
        print("  direct retrieve LTM  : SKIP")
    else:
        print(f"  direct retrieve LTM  : {'PASS' if ltm_hits > 0 else 'FAIL'}")

    if stm_ok and ltm_ok and (ltm_hits is None or ltm_hits > 0):
        print("\nRESULT: STM y LTM funcionando correctamente.")
    else:
        print("\nRESULT: ATTENTION — revisar STM/LTM en runtime.")

    return {
        "seed_session": session_a,
        "work_session": session_b,
        "preference_key": preference_key,
        "marker": marker,
        "household": household,
        "seed_response": resp1,
        "stm_question_response": resp2,
        "stm_recall_response": resp3,
        "ltm_recall_response": resp4,
        "ltm_hits": ltm_hits,
        "stm_ok": stm_ok,
        "ltm_ok": ltm_ok,
    }


if __name__ == "__main__":
    test_stm_ltm_unilateral()
