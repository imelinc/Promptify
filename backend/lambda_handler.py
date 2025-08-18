import json, os, re, logging, base64
import boto3

logging.getLogger().setLevel(logging.INFO)

REGION   = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
MAX_TOK  = int(os.environ.get("MAX_TOKENS", "400"))

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

ALLOWED_ORIGINS = {
    "https://d24e3kao48qx0i.cloudfront.net",  # CloudFront
}

def _allow_origin(origin):
    return origin if origin in ALLOWED_ORIGINS else "https://d24e3kao48qx0i.cloudfront.net"

def _resp(status, body, origin="*"):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": _allow_origin(origin),
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
            "Vary": "Origin"
        },
        "body": json.dumps(body, ensure_ascii=False)
    }

def _safe_trim(text, max_chars=4000):
    text = re.sub(r"\s+\n", "\n", text).strip()
    return text[:max_chars]

def lambda_handler(event, context):
    origin = (event.get("headers") or {}).get("origin") or (event.get("headers") or {}).get("Origin") or "*"

    # Preflight CORS
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(200, {"ok": True}, origin)

    try:
        raw_body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            raw_body = base64.b64decode(raw_body).decode("utf-8")
        data = json.loads(raw_body)

        rol      = (data.get("rol") or "").strip()
        tarea    = (data.get("tarea") or "").strip()
        formato  = (data.get("formato") or "").strip()
        tono     = (data.get("tono") or "").strip()
        contexto = (data.get("contexto") or "").strip()

        missing = [k for k,v in {"rol":rol,"tarea":tarea,"formato":formato,"tono":tono}.items() if not v]
        if missing:
            return _resp(400, {"error": f"Faltan campos: {', '.join(missing)}"}, origin)

        system_msg = (
            "Eres un DISEÑADOR DE PROMPTS experto. Devuelve SOLO un PROMPT final listo para otro modelo. "
            "Sé creativo en la estructura (no plantilla fija). Máximo ~400 tokens. Sin explicaciones."
        )

        user_msg = f"""
Diseña un PROMPT para que otro modelo ejecute la tarea.

[Rol objetivo] {rol}
[Tarea específica] {tarea}
[Formato deseado] {formato}
[Tono/estilo] {tono}
[Contexto opcional] {contexto or "N/A"}
"""

        request = {
            "modelId": MODEL_ID,
            "inferenceConfig": {"maxTokens": MAX_TOK, "temperature": 0.7, "topP": 0.9},
            "system":   [{"text": system_msg}],
            "messages": [{"role": "user", "content": [ {"text": user_msg} ]}]
        }

        result = bedrock.converse(**request)
        parts = result.get("output", {}).get("message", {}).get("content", [])
        text  = "".join(p.get("text","") for p in parts)
        text  = _safe_trim(text, max_chars=4000)

        if not text:
            return _resp(502, {"error":"Respuesta vacía del modelo"}, origin)

        return _resp(200, {"prompt": text}, origin)

    except Exception as e:
        logging.exception("Error en Lambda")
        return _resp(500, {"error": "lambda_error", "detail": str(e)}, origin)
