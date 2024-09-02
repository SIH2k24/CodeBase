import os
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import load_model
import requests
import speech_recognition as sr
import librosa
from pydub import AudioSegment
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

# Configure logging to show only errors
logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Twilio credentials
account_sid = "AC7f41acdba81736c349ab2a60622b97a4"
auth_token = "fc69f0823f5a7a4d031a48c6d9ab4440"
client = Client(account_sid, auth_token)

# Load the trained model
try:
    model = load_model('help_detection_model.h5')
except Exception as e:
    logger.error(f'Error loading model: {str(e)}')
    raise

@app.route('/', methods=['GET'])
def home():
    return jsonify({'message': 'Flask server is running!'})

def send_call():
    try:
        live_location = "https://maps-eta-gilt.vercel.app/map"
        twiml = VoiceResponse()
        twiml.say(voice='alice', message='Hello! Your friend might be in big trouble. Please check the SMS message.')

        call = client.calls.create(
            twiml=twiml,
            to='+918618541131',
            from_='+16122844698'
        )
        logger.error(f'Call initiated. Call SID: {call.sid}')

    except Exception as e:
        logger.error(f'Failed to send call alert: {str(e)}')

@app.route('/send-call', methods=['POST'])
def send_call_endpoint():
    try:
        send_call()
        return jsonify({'message': 'Call initiated successfully.'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def send_sms():
    try:
        live_location = "https://maps-eta-gilt.vercel.app/map"

        client.messages.create(
            from_='+16122844698',
            to='+918618541131',
            body=f'Your friend is in big trouble, please check out the link: {live_location}'
        )
        logger.error('SMS alert sent successfully.')

    except Exception as e:
        logger.error(f'Failed to send SMS alert: {str(e)}')

@app.route('/send-sms', methods=['POST'])
def send_sms_endpoint():
    try:
        send_sms()
        return jsonify({'message': 'SMS sent successfully.'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/predict', methods=['POST'])
    
def predict():
    print("Hit predit")
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    try:
        original_file_path = os.path.join('uploads', file.filename)
        file.save(original_file_path)

        audio_format = original_file_path.split('.')[-1]
        if file.filename.endswith('.3gp'):
            audio = AudioSegment.from_file(original_file_path, format='3gp')
            wav_file_path = original_file_path.replace('.3gp', '.wav')
            audio.export(wav_file_path, format='wav')
        else:
            wav_file_path = original_file_path

        text, keyword_detected, avg_pitch, avg_energy = preprocess_audio(wav_file_path)
        emotion_response = get_emotion_probs(wav_file_path)

        if isinstance(emotion_response, list) and len(emotion_response) > 0:
            emotion_probs = np.array([emotion['score'] for emotion in emotion_response], dtype=np.float32)
            emotion_probs = emotion_probs.reshape(1, -1)

            if emotion_probs.shape[1] < 8:
                padding = np.zeros((1, 8 - emotion_probs.shape[1]), dtype=np.float32)
                emotion_probs = np.concatenate([emotion_probs, padding], axis=1)
        else:
            return jsonify({'error': 'Invalid or empty response from Hugging Face API'}), 500

        keyword_input = np.array([[int(keyword_detected)]], dtype=np.float32)
        pitch_input = np.array([[avg_pitch]], dtype=np.float32)
        energy_input = np.array([[avg_energy]], dtype=np.float32)
        emotion_probs = emotion_probs.astype(float)

        if keyword_detected:
            prediction = model.predict([keyword_input, pitch_input, energy_input, emotion_probs])
            label = (prediction > 0.5).astype(int)[0][0]
            result = "Help" if label == 1 else "No Help"
            logger.error(f"Help detection result: {result}")
            
            if result == "Help":
                send_alert()
        else:
            result = "No keyword detected. The audio indicates 'No Help'."
            logger.error("Help detection result: No Help (No keyword detected)")

        os.remove(original_file_path)
        if original_file_path != wav_file_path:
            os.remove(wav_file_path)

        return jsonify({
            'text': text,
            'keyword_detected': keyword_detected,
            'avg_pitch': float(avg_pitch),
            'avg_energy': float(avg_energy),
            'emotion_probs': emotion_probs.tolist(),
            'result': result
        })

    except Exception as e:
        logger.error(f'An error occurred during processing: {str(e)}')
        return jsonify({'error': 'An error occurred', 'details': str(e)}), 500

def send_alert():
    try:
        live_location = "https://maps-eta-gilt.vercel.app/map"
        twiml = VoiceResponse()
        twiml.say(voice='alice', message='Hello! Your friend might be in big trouble. Please check the SMS message.')

        client.messages.create(
            from_='+16122844698',
            to='+918618541131',
            body=f'Your friend is in big trouble, please check out the link: {live_location}'
        )

        call = client.calls.create(
            twiml=twiml,
            to='+918618541131',
            from_='+16122844698'
        )
        logger.error(f'Alert sent. Call SID: {call.sid}')

    except Exception as e:
        logger.error(f'Failed to send alert: {str(e)}')

def preprocess_audio(audio_file_path):
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_file_path) as source:
        audio_data = recognizer.record(source)

    try:
        text = recognizer.recognize_google(audio_data)
        keyword_detected = detect_keywords(text)
        
    except sr.UnknownValueError:
        text = ""
        keyword_detected = False
    except sr.RequestError as e:
        text = ""
        keyword_detected = False

    avg_pitch, avg_energy = analyze_pitch_and_volume(audio_file_path)
    return text, keyword_detected, avg_pitch, avg_energy

def detect_keywords(text):
    return any(keyword in text.lower() for keyword in keywords)

def analyze_pitch_and_volume(audio_path):
    y, sr = librosa.load(audio_path)
    pitches, magnitudes = librosa.piptrack(y=y, sr=sr)

    pitch_values = []
    for i in range(pitches.shape[1]):
        pitch = pitches[:, i]
        pitch = pitch[pitch > 0]
        if len(pitch) > 0:
            pitch_values.append(np.mean(pitch))

    energy = np.sum(librosa.feature.rms(y=y))
    avg_pitch = np.mean(pitch_values) if pitch_values else 0
    avg_energy = energy / len(y)

    return avg_pitch, avg_energy

def get_emotion_probs(filename):
    API_URL = "https://api-inference.huggingface.co/models/ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition"
    headers = {"Authorization": "Bearer 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"}

    with open(filename, "rb") as f:
        data = f.read()
    try:
        response = requests.post(API_URL, headers=headers, data=data)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f'Error during Hugging Face API request: {str(e)}')
        raise

# Define an extensive list of keywords and phrases for help detection
keywords = [
    "help", "emergency", "assist", "danger", "scream", "rescue", "save me", "trouble", "call 911",
    "need help", "need assistance", "I'm in danger", "can't breathe", "can't move", "someone help",
    "help me", "get me out", "I'm trapped", "I'm hurt", "I'm injured", "can't escape", 
    "please help", "come quickly", "I'm in trouble", "call for help", "it's an emergency", 
    "I'm scared", "something's wrong", "get help", "I'm lost", "lost", "where am I", 
    "find me", "I'm bleeding", "need medical help", "send help", "is anyone there", "is anyone around",
    "can someone hear me", "help needed", "urgent help", "can't find my way", "I need help", 
    "please assist", "there's a problem", "immediate help", "get the police", "get the doctor", 
    "send an ambulance", "urgent", "come quickly", "it's urgent", "get me out of here", 
    "I'm stuck", "I'm being followed", "I'm being attacked", "dangerous situation", "emergency situation",
    "can't see", "can't hear", "I'm blind", "I'm deaf", "can't feel my legs", "I'm scared", 
    "I need help immediately", "something's wrong", "help now", "please come", "it's a life or death situation",
    "I think I'm in danger", "emergency help needed", "I'm in serious trouble", "immediate assistance required"
]

if __name__ == '__main__':
    if not os.path.exists('uploads'):
        os.makedirs('uploads')
    
    app.run(host='0.0.0.0', port=5000)
