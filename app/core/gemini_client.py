from google import genai
from dotenv import load_dotenv
import os
from app.core.env_utils import get_env_variable

load_dotenv()

api_key = get_env_variable("GEMINI_API_KEY")

client = genai.Client(api_key= api_key)

model_name = get_env_variable("GEMINI_MODEL_NAME")

def generate_chat_response(history: list):
    gemini_history = []
    for msg in history:
        if msg["role"] == "assistant":
            new_role = "model"
        else:
            new_role = msg["role"]

        gemini_history.append({
            "role": new_role,
            "parts": [{"text": msg["content"]}]
        })

    response = client.models.generate_content(
        model= model_name,
        contents= gemini_history
    )
    return response.text