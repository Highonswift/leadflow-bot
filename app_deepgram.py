import os
import io
import tempfile
import time
import numpy as np
from threading import Thread

import logging
from dotenv import load_dotenv

import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
from deepgram import DeepgramClient, LiveTranscriptionEvents
import google.generativeai as genai
import requests

from db_manager import initialize_db, getAgentDetails, getMessages, addMessage, createConversation

# --- Initialization ---
load_dotenv()
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-very-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///conversations.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

logging.basicConfig(level=logging.INFO)
db = SQLAlchemy(app)
socketio = SocketIO(app, async_mode='eventlet')

# --- API Clients Initialization ---
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
deepgram_client = DeepgramClient(DEEPGRAM_API_KEY)
deepgram_connections = {} # To hold a connection for each user session

# --- API Clients Initialization (TTS and LLM) ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
generation_config = {"temperature": 0.7, "top_p": 1, "top_k": 1, "max_output_tokens": 2048}

# --- ElevenLabs ---
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

# --- General ---
initialize_db(os.getenv("DATABASE_URL"))
agent_details = {}
os.makedirs("sessions", exist_ok=True)

# --- Helper Functions (Unchanged) ---
def get_gemini_response(session_id, user_text):
    with app.app_context():
        history = getMessages(session_id)
        print("history", history)
        
        prompt = agent_details[session_id]['prompt']

        gemini_model = genai.GenerativeModel('gemini-2.5-flash', generation_config=generation_config, system_instruction=prompt)
        chat = gemini_model.start_chat(history=history)
        
        response = chat.send_message(user_text)
        model_response_text = response.text
        
        user_message = addMessage(session_id, 'user', user_text)
        model_message = addMessage(session_id, 'model', model_response_text)
        
        return model_response_text

def stream_elevenlabs_response(text, sid):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream"
    headers = {"Accept": "audio/mpeg", "Content-Type": "application/json", "xi-api-key": ELEVENLABS_API_KEY}
    params = {'optimize_streaming_latency': 3}
    data = {"text": text, "model_id": "eleven_turbo_v2", "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}
    try:
        with requests.post(url, headers=headers, json=data, stream=True, params=params) as response:
            if response.status_code == 200:
                for chunk in response.iter_content(chunk_size=4096):
                    if chunk: socketio.emit('audio_chunk', chunk, to=sid)
                socketio.emit('agent_response', {'text': text}, to=sid)
                socketio.emit('audio_stream_end', to=sid)
                saveAudio(chunk, "mp3", sid)
            else: logging.error(f"ElevenLabs API error: {response.status_code} - {response.text}")
    except Exception as e: logging.error(f"Error streaming from ElevenLabs: {e}")

# --- Flask & SocketIO Routes ---
@app.route('/<agent_id>')
def index(agent_id):
    agentData = getAgentDetails(agent_id)
    agent_details[agent_id] = agentData
    return render_template('index.html', name=agentData['name'], subtext=agentData['subtext'], id=agent_id)

# @app.route('/')
# def index():
#     return render_template('400error.html')


@socketio.on('connect')
def handle_connect(*args, **kwargs):
    with app.app_context(): db.create_all()

    agent_id = request.args.get('agent_id')
    agentData = agent_details[agent_id]
    agent_details[request.sid] = agentData

    createConversation(agent_id, request.sid)

    welcome_text = agentData['welcome_message']
    socketio.start_background_task(stream_elevenlabs_response, welcome_text, request.sid)
    handle_start_stream(request.sid)
    

# @socketio.on('start_stream')
# def handle_start_stream():
#     sid = request.sid

def handle_start_stream(sid):    
    # Use the modern, correct 'listen.websocket' method
    deepgram_connection = deepgram_client.listen.websocket.v("1")
    deepgram_connections[sid] = {'connection': deepgram_connection, 'full_transcript': '', 'partial_transcript': ''}

    def on_message(self, result, **kwargs):
        transcript = result.channel.alternatives[0].transcript
        if len(transcript) == 0:
            return

        print(transcript, result.is_final, result.speech_final)

        transcript_sofar = deepgram_connections[sid]['partial_transcript']
        transcript_new = transcript_sofar + ' ' + transcript
        if result.is_final:
            deepgram_connections[sid]['partial_transcript'] = transcript_new
        
        # Update the UI with the interim (live) part
        socketio.emit('transcript_update', {'transcript': transcript_new}, to=sid)
        deepgram_connections[sid]['full_transcript'] = transcript_new

    def on_error(self, error, **kwargs):
        logging.error(f"Deepgram error for SID {sid}: {error}")

    deepgram_connection.on(LiveTranscriptionEvents.Transcript, on_message)
    deepgram_connection.on(LiveTranscriptionEvents.Error, on_error)

    options = {
        # "model": "nova-2", 
        # "model": "nova-2-conversational",
        # "language": "en-US",
        
        "model": "nova-3",
        "language": "en-IN", 

        "smart_format": True, 
        "encoding": "linear16", 
        "sample_rate": 16000,
        "interim_results": True,
        "endpointing": 1000
    }
    deepgram_connection.start(options)
    logging.info(f"Deepgram connection started for SID: {sid}")

@socketio.on('audio_chunk')
def handle_audio_chunk(chunk):
    sid = request.sid
    if sid in deepgram_connections:
        # saveAudio(chunk, "wav", sid)
        saveAudio(chunk, "pcm", sid)
        deepgram_connections[sid]['connection'].send(chunk)
        deepgram_connections[sid]['last_input_time'] = time.time()

@socketio.on('stop_stream')
def handle_stop_stream():
    sid = request.sid
    if sid in deepgram_connections:
        
        model_response = "Sorry, can you please repeat?"
        final_text = deepgram_connections[sid]['full_transcript'].strip()
        
        # Reset for the next utterance
        deepgram_connections[sid]['connection'].finish()
        handle_start_stream(sid)
        
        if final_text:
            print(sid, final_text)
            model_response = get_gemini_response(sid, final_text)
            
        logging.info(f"Final transcript for SID {sid}: {final_text}")
        socketio.start_background_task(stream_elevenlabs_response, model_response, sid)
        
        logging.info(f"Deepgram connection finished for SID: {sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in deepgram_connections:
        deepgram_connections[sid]['connection'].finish()
        del deepgram_connections[sid]
        logging.info(f"Deepgram connection cleaned up for SID: {sid}")

def saveAudio(audio_chunk, audio_format, session_id):
    if True:
        return

# def saveAudio(audio_chunk, audio_format, session_id):
#     output_dir = "sessions"
#     output_filename = os.path.join(output_dir, f'{session_id}.wav')

#     try:
#         # Load the audio chunk using pydub.
#         # This handles decoding the different formats (mp3, wav, etc.).
#         if audio_format == 'pcm':
#             # You'll need to know the sample rate and sample width for raw PCM
#             # For Deepgram, it's often 16000 Hz, 16-bit
#             # You might need to adjust these parameters
#             # For this example, let's assume 16kHz, 16-bit mono
#             audio_segment = AudioSegment(
#                 data=audio_chunk,
#                 sample_width=2, # 16-bit
#                 frame_rate=16000,
#                 channels=1
#             )
#         elif audio_format == "mp3":
#             # Create a temporary file to save the MP3 chunk
#             with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_mp3:
#                 temp_mp3.write(audio_chunk)
#                 temp_mp3_path = temp_mp3.name

#             # Now, pydub can read the temporary file from disk
#             audio_segment = AudioSegment.from_file(temp_mp3_path, format="mp3")
            
#             # Clean up the temporary file
#             os.remove(temp_mp3_path)
#         else:
#             # For formats like 'mp3' or 'wav', pydub can directly read the bytes
#             audio_segment = AudioSegment.from_file(io.BytesIO(audio_chunk), format=audio_format)
            
#         # Check if the session file already exists
#         if os.path.exists(output_filename):
#             # If it exists, load the existing audio and append the new chunk
#             existing_audio = AudioSegment.from_wav(output_filename)
#             final_audio = existing_audio + audio_segment
#         else:
#             # If it's the first chunk, just use it as the starting audio
#             final_audio = audio_segment

#         # Export the combined audio to the final WAV file
#         final_audio.export(output_filename, format='wav')
        
#         print(f"Appended audio chunk to {output_filename}")

#     except Exception as e:
#         print(f"Error saving audio for session {session_id}: {e}")

# def saveAudio(audio_chunk, fmt, sid):
#     try:
#         file_path = f"sessions/conversation_{sid}.mp3"

#         if not os.path.exists(file_path):
#             if fmt == "mp3":
#                 with open(file_path, "wb") as f:
#                     f.write(audio_chunk)
#             else:
#                 seg = AudioSegment.from_file(io.BytesIO(audio_chunk), format=fmt)
#                 seg.export(file_path, format="mp3")
#             return file_path

#         # If file already exists → append
#         if fmt == "mp3":
#             existing = AudioSegment.from_file(file_path, format="mp3")
#             new_seg = AudioSegment.from_file(io.BytesIO(audio_chunk), format="mp3")
#             combined = existing + new_seg
#         else:
#             existing = AudioSegment.from_file(file_path, format="mp3")
#             new_seg = AudioSegment.from_file(io.BytesIO(audio_chunk), format=fmt)
#             combined = existing + new_seg

#         combined.export(file_path, format="mp3")
#         return file_path
#     except Exception as e:
#         logging.error(f"Error while saving audio {sid}: {e}")


# def saveAudio(audio_chunk, fmt, sid):
#     file_path = f"sessions/conversation_{sid}.wav"

#     # If MP3 → convert to WAV bytes first
#     if fmt == "mp3":
#         seg = AudioSegment.from_file(io.BytesIO(audio_chunk), format="mp3")
#         audio_chunk = seg.set_channels(1).set_frame_rate(16000).set_sample_width(2).raw_data
#     elif fmt != "wav":
#         raise ValueError("Only 'wav' and 'mp3' formats supported")

#     # If file doesn't exist → create new WAV
#     if not os.path.exists(file_path):
#         with wave.open(file_path, "wb") as wf:
#             wf.setnchannels(1)       # mono
#             wf.setsampwidth(2)       # 16-bit samples
#             wf.setframerate(16000)   # 16kHz sample rate
#             wf.writeframes(audio_chunk)
#     else:
#         # Append → read existing + add new frames
#         with wave.open(file_path, "rb") as wf:
#             params = wf.getparams()
#             existing_frames = wf.readframes(wf.getnframes())

#         with wave.open(file_path, "wb") as wf:
#             wf.setparams(params)
#             wf.writeframes(existing_frames + audio_chunk)

#     return file_path

def generate_silence(duration_ms=20, sample_rate=16000):
    """Generate PCM16 silence of given duration in milliseconds"""
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    silence = np.zeros(num_samples, dtype=np.int16)
    return silence.tobytes()

def startDeepgramConnectionIdleCheck():
    def idle_loop():
        while True:
            now = time.time()
            
            for sid, conn_info in deepgram_connections.items():
                last_time = conn_info.get('last_input_time')
                
                # If no activity for 3+ seconds
                if last_time is None or (now - last_time) > 3:
                    try:
                        dummy_chunk = generate_silence(duration_ms=20)
                        conn_info['connection'].send(dummy_chunk)
                        conn_info['last_input_time'] = now
                    except Exception as e:
                        print(f"Error sending idle silence to SID {sid}: {e}")
            time.sleep(4)  # check every 2 seconds

    t = Thread(target=idle_loop, daemon=True)
    t.start()

if __name__ == '__main__':
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        pass  # parent process, do nothing
    else:
        startDeepgramConnectionIdleCheck()

    socketio.run(app, debug=True)