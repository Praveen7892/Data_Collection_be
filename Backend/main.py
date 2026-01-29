from flask import Flask, request, jsonify, Response
from main_utils import *
from bson import ObjectId
from bson.json_util import dumps
from flask_cors import CORS
import json
import os
import time


last_state = None
latest_reports = None

app = Flask(__name__)
CORS(app)
CORS(app, origins=["http://localhost:3000"])


### Get all cameras ###
@app.route('/camera/get_all_cameras', methods=['GET'])
def get_cameras():
    message, response, status_code = get_cameras_utils()
    return jsonify({"message":message, "response":response,"status_code":status_code}), status_code


### Camera initialization ###
@app.route('/camera/initialization', methods=['POST'])
def initialization():
    data = request.json
    message, response, status_code = initialization_utils(data)
    return jsonify({"message":message, "response":response,"status_code":status_code}), status_code



### Capture Images ###
@app.route('/capture/click_capture', methods=['POST'])
def capture():
    data = request.json
    message, response, status_code = capture_util(data)
    return jsonify({"message":message, "response":response,"status_code":status_code}), status_code


@app.route('/capture/get_captured_images', methods=['GET'])
def get_captured_images():    
    message, response, status_code = get_captured_images_util()
    return jsonify({"message":message, "response":response,"status_code":status_code}), status_code




@app.route('/')
def home():
    return "Backend running........!!!"

if __name__ == "__main__":

    os.makedirs("./../Bucket",exist_ok=True)

    app.run(host="0.0.0.0", port=5000, debug=True)




