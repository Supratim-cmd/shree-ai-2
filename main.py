import os
from fastapi import FastAPI, WebSocket
import uvicorn
from openai import OpenAI

app = FastAPI()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

@app.get("/")
def home():
    return {"status": "Shree AI is online"}

@app.websocket("/voice")
async def voice_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        try:
            audio_data = await websocket.receive_bytes()
            with open("input.wav", "wb") as f:
                f.write(audio_data)
            with open("input.wav", "rb") as f:
                transcript = client.audio.transcriptions.create(model="whisper-1", file=f)
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": transcript.text}]
            )
            ai_text = response.choices[0].message.content
            speech = client.audio.speech.create(model="tts-1", voice="nova", input=ai_text)
            await websocket.send_bytes(speech.content)
        except:
            break

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
