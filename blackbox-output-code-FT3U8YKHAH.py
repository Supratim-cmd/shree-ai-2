from fastapi import FastAPI, WebSocket, Depends
from fastapi.security import HTTPBearer
import redis
import openai
import azure.cognitiveservices.speech as speechsdk
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dh
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import os

app = FastAPI()
redis_client = redis.Redis(host='localhost', port=6379, db=0)
security = HTTPBearer()

# E2EE: Diffie-Hellman Key Exchange
@app.post("/handshake")
async def e2ee_handshake(client_public_key: bytes):
    # Generate server DH keys
    parameters = dh.generate_parameters(generator=2, key_size=2048)
    server_private_key = parameters.generate_private_key()
    server_public_key = server_private_key.public_key()
    
    # Derive shared secret
    shared_key = server_private_key.exchange(dh.DHPublicKey.from_public_bytes(client_public_key))
    derived_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b'handshake').derive(shared_key)
    
    # Store in Redis (encrypted session)
    session_id = os.urandom(16).hex()
    redis_client.setex(session_id, 3600, derived_key.hex())  # Expire in 1 hour
    
    return {"session_id": session_id, "server_public_key": server_public_key.public_bytes_raw()}

# WebSocket for real-time voice streaming
@app.websocket("/voice/{session_id}")
async def voice_stream(websocket: WebSocket, session_id: str):
    await websocket.accept()
    derived_key = bytes.fromhex(redis_client.get(session_id).decode())
    
    while True:
        # Receive E2EE-encrypted STT audio
        encrypted_data = await websocket.receive_bytes()
        audio_data = decrypt_aes(encrypted_data, derived_key)  # Decrypt
        
        # STT (Azure example)
        speech_config = speechsdk.SpeechConfig(subscription=os.getenv("AZURE_KEY"), region="eastus")
        audio_input = speechsdk.AudioConfig(use_default_microphone=False)
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_input)
        result = recognizer.recognize_once(audio_data)
        text = result.text
        
        # GPT-4o processing
        response = openai.ChatCompletion.create(model="gpt-4o", messages=[{"role": "user", "content": text}])
        ai_text = response.choices[0].message.content
        
        # TTS (OpenAI example)
        tts_audio = openai.Audio.create(model="tts-1-hd", input=ai_text, voice="alloy").data
        
        # Encrypt and send back
        encrypted_response = encrypt_aes(tts_audio, derived_key)
        await websocket.send_bytes(encrypted_response)

# Helper functions for AES-256 E2EE
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

def encrypt_aes(data: bytes, key: bytes) -> bytes:
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    padded_data = data + b'\0' * (16 - len(data) % 16)  # PKCS7 padding
    return iv + encryptor.update(padded_data) + encryptor.finalize()

def decrypt_aes(encrypted: bytes, key: bytes) -> bytes:
    iv, ciphertext = encrypted[:16], encrypted[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()