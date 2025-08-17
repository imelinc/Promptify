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

def _safe_trim(text, max_chars=4000):
    text = re.sub(r"\s+\n", "\n", text).strip()
    return text[:max_chars]

def lambda_handler(event, context):
    origin = event.get("headers", {}).get("origin") or event.get("headers", {}).get("Origin") or "*"

    # Preflight CORS
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(200, {"ok": True}, origin)

    try:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            import base64
            body = base64.b64decode(body).decode("utf-8")
        data = json.loads(body)

        rol = (data.get("rol") or "").strip()
        tarea = (data.get("tarea") or "").strip()
        formato = (data.get("formato") or "").strip()
        tono = (data.get("tono") or "").strip()
        contexto = (data.get("contexto") or "").strip()

        # Validaciones mínimas
        missing = [k for k, v in {"rol": rol, "tarea": tarea, "formato": formato, "tono": tono}.items() if not v]
        if missing:
            return _resp(400, {"error": f"Faltan campos: {', '.join(missing)}"}, origin)

        # 🧠 System: pedir a Haiku que DISEÑE un prompt final (no la respuesta a la tarea)
        system_msg = (
            "Eres un DISEÑADOR DE PROMPTS experto. Tu salida debe ser únicamente un PROMPT final "
            "listo para usar en otro modelo de IA, no una explicación ni la respuesta a la tarea.\n"
            "Requisitos estrictos:\n"
            "- Longitud máxima aproximada: 400 tokens.\n"
            "- Varía la estructura: usa diferentes estilos (secciones, bullets, pasos, mando directo, preguntas guía), "
            "  evita plantillas rígidas y repetidas.\n"
            "- Adapta el prompt al rol, tarea, formato y tono dados.\n"
            "- Si el usuario aportó contexto, úsalo con criterio.\n"
            "- Evita auto-referencias (no digas 'como IA...'), no agregues comentarios meta, ni notas para el usuario.\n"
            "- Devuelve SOLO el PROMPT final."
        )

        # 🗣️ User: pasamos señales claras, pero dejamos libertad creativa al modelo
        user_msg = f"""
Diseña un PROMPT para que otro modelo ejecute la siguiente tarea.

[Rol objetivo] {rol}
[Tarea específica] {tarea}
[Formato deseado] {formato}
[Tono/estilo] {tono}
[Contexto opcional] {contexto or "N/A"}

Lineamientos de calidad:
- El prompt debe guiar al modelo a producir una salida de alta calidad acorde al formato indicado.
- Incluye criterios de calidad/verificación si corresponde (p.ej., pasos, validaciones, límites).
- Propón aclaraciones/preguntas en el prompt solo si son imprescindibles para ejecutar bien la tarea.
- No excedas ~400 tokens.
"""

        request = {
            "modelId": MODEL_ID,
            "inferenceConfig": {
                "maxTokens": MAX_TOKENS,
                "temperature": 0.7,  # ↑ variación en estilo/estructura
                "topP": 0.9
            },
            "messages": [
                {"role": "user", "content": [{"text": user_msg}]}
            ],
            "system": [{"text": system_msg}],
        }

        result = bedrock.converse(**request)
        parts = result.get("output", {}).get("message", {}).get("content", [])
        text = "".join(p.get("text", "") for p in parts)
        text = _safe_trim(text, max_chars=4000)

        # Recorte defensivo: si se pasó de largo, acotamos a ~4000 chars (≈ <=400 tokens en promedio)
        return _resp(200, {"prompt": text})

    except Exception as e:
        return _resp(500, {"error": str(e)}, origin)
