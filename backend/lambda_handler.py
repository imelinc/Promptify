import json
import os
import re
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "400"))

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

def _resp(status, body, origin="*"):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "OPTIONS,POST"
        },
        "body": json.dumps(body, ensure_ascii=False)
    }

def _build_system_prompt():
    return (
        "Eres un generador de prompts. Devuelve SOLO el prompt final, claro, "
        "accionable y conciso, sin explicaciones. No excedas el límite."
    )

def _safe_trim(text, max_chars=3000):
    text = re.sub(r"\s+\n", "\n", text).strip()
    return text[:max_chars]

def lambda_handler(event, context):
    origin = event.get("headers", {}).get("origin") or event.get("headers", {}).get("Origin") or "*"

    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(200, {"ok": True}, origin)

    try:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            import base64
            body = base64.b64decode(body).decode("utf-8")
        data = json.loads(body)

        # Espera los mismos campos que arma tu frontend:
        # contexto, indicaciones, lenguaje, uso
        contexto = data.get("contexto", "")
        indicaciones = data.get("indicaciones", "No excedas 400 tokens.")
        lenguaje = data.get("lenguaje", "Español")
        uso = data.get("uso", "")  # acá podés pasar el prompt armado si quisieras

        if not (contexto or uso):
            return _resp(400, {"error": "Faltan datos. Envía al menos 'contexto' o 'uso'."}, origin)

        system_prompt = _build_system_prompt()

        # Si 'uso' ya es un prompt armado, lo usamos como mensaje del usuario;
        # en caso contrario, ensamblamos uno básico con el contexto/indicaciones.
        user_prompt = uso or f"""
[OBJETIVO]
Generar un prompt utilizable por otro modelo.

[CONTEXTO]
{contexto}

[REQUISITOS]
{indicaciones}

[IDIOMA]
{lenguaje}
"""
        user_prompt = _safe_trim(user_prompt)

        request = {
            "modelId": MODEL_ID,
            "inferenceConfig": {
                "maxTokens": MAX_TOKENS,
                "temperature": 0.5,
                "topP": 0.9
            },
            "messages": [
                {"role": "user", "content": [{"text": user_prompt}]}
            ],
            "system": [{"text": system_prompt}],
        }

        result = bedrock.converse(**request)
        parts = result.get("output", {}).get("message", {}).get("content", [])
        text = "".join(p.get("text", "") for p in parts)
        text = _safe_trim(text, max_chars=3000)

        return _resp(200, {"prompt": text}, origin)

    except Exception as e:
        return _resp(500, {"error": str(e)}, origin)
