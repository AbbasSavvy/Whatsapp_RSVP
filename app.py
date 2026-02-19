import os
import json
from flask import Flask, request
from dotenv import load_dotenv
from whatsapp import send_message, send_button_message
from sheets import save_rsvp
from conversation import handle_message, RSVP_BUTTONS

load_dotenv()

app = Flask(__name__)

session = {}

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if mode == "subscribe" and token == os.getenv("VERIFY_TOKEN"):
        print("Webhook verified!")
