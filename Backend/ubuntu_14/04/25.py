
import zipfile
import psutil
import secrets
import string
import requests
import bson
import os
import jinja2
import pdfkit
import base64
import requests
import smtplib
import ssl
import threading
import json
import bson
import cv2
import os
from collections import defaultdict
from flask import jsonify
from datetime import datetime
from main_helper import MongoDBHelper, RedisHelper
from constants import *
from datetime import datetime, timedelta
from bson import ObjectId
from pymongo import DESCENDING
import pandas as pd
import requests
from fpdf import FPDF
from flask import Response, send_file,  request
from reportlab.pdfgen import canvas
from PIL import Image  # Using PIL to check image format
import time
from main_helper import AppConfig
from io import BytesIO
from fpdf import FPDF
from PIL import Image  # Using PIL to check image format
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
     JWTManager, create_access_token, jwt_required, get_jwt_identity
)


from concurrent.futures import ThreadPoolExecutor, as_completed
from pymongo import ASCENDING, DESCENDING




mongo_helper = MongoDBHelper()
redis_helper = RedisHelper()







class Encoder(json.JSONEncoder):
    def default(self, obj):
        # Convert MongoDB ObjectId to string
        if isinstance(obj, ObjectId):
            return str(obj)
        # Convert datetime objects to string in ISO format
        elif isinstance(obj, datetime):
            return obj.isoformat()
        # If object is of other types, use default serialization
        return super().default(obj)





####################### USER Utils ######################################
def get_all_users_data():
    users = mongo_helper.read_collection(USER_COLLECTION)
    # print(users)
    user_data = [i for i in users.find()]
    # print(user_data)

    return "Success", {"data":user_data}, 200
    
def login_user(data):
    email = data.get('email') # 	
    password = data.get('password')

    if not email or not password:
        return "Invalid email or password", {"count": 0, "role": None}, 401

    users = mongo_helper.read_collection(USER_COLLECTION)

    # Find user by email
    user_data = users.find_one({"email": email})

    # if not user_data or not check_password_hash(user_data.get('password', ''), password):
    # 	return "Invalid email or password", {}, 401

    # # Generate JWT token
    access_token = create_access_token(identity=email)

    # # Update the user document with the token
    # users.update_one(
    # 	{"email": email},
    # 	{"$set": {"token": access_token}}
    # )
    if not user_data:
        # User not found
        return "Invalid email or password", {"count": 0, "role": None}, 401

    # Check if the account is locked
    if user_data.get("account_locked", False):
        return (
            "Account is locked. Please contact admin.",
            {"count": user_data.get("invalid_login_count", 3), "role": user_data.get("role")},
            403
        )

    # Check password
    if not check_password_hash(user_data.get('password', ''), password):
        # Increment the invalid login count
        invalid_count = user_data.get("invalid_login_count", 0) + 1

        if invalid_count >= 3:
            # Lock the account
            users.update_one(
                {"email": email},
                {
                    "$set": {
                        "account_locked": True,
                        "invalid_login_count": invalid_count,
                        "lock_time": DATE_FORMAT  # Optionally record the lock time
                    }
                }
            )
            return (
                "Account is locked. Please contact admin.",
                {"count": invalid_count, "role": user_data.get("role")},
                403
            )

        # Update invalid login count
        users.update_one(
            {"email": email},
            {
                "$inc": {"invalid_login_count": 1},  # Increment the invalid login count
                "$set": {"last_failed_login": DATE_FORMAT}  # Record the last failed login time
            }
        )
        return "Invalid email or password", {"count": invalid_count, "role": user_data.get("role")}, 401


    # Reset invalid login count upon successful login
    users.update_one(
        {"email": email},
        {"$set": {"invalid_login_count": 0}}
    )

    response = {
        "user_id": str(user_data.get("_id")),
        "user":user_data.get("full_name"),
        "role": user_data.get("role"),
        "token": access_token
    }

    return "Success", response, 200

########### Forgot Password API ##################################################


def generate_passkey(length=8):
    """Generates a unique and secure passkey"""
    characters = string.ascii_letters + string.digits  # A-Z, a-z, 0-9
    return ''.join(secrets.choice(characters) for _ in range(length))


def send_passkey_thread(sender_email, receiver_email, password, subject, body, files=None):
    """Function to send an email with optional attachments in a separate thread"""

    # Create email message
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    # Send email
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, message.as_string())
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

def send_passkey_mail_util(data):
    email = data.get("email")  
    # pas
    passkey = data.get("passkey") 

    if not email or not passkey:
        return "Error: Email or passkey missing", {}, 400

    print(">>>>>>>> Passkey:", passkey)

    # Email details
    subject = "Factree.Ai - Reset Password Through Passkey"
    body = f"""
    Hello Admin,

    Your passkey to reset password  is: {passkey}

    This passkey is valid for only 10 minutes.

    If you didn't request this, please ignore this email.

    Best Regards,  
    Factree.ai
    """
    send_passkey_thread(SENDER_EMAIL, email, SENDER_EMAIL_PASSWORD, subject, body, [])

    return f"Passkey has been sent to {email}.", {"passkey": passkey}, 200


def forgot_password(data):
    """Handles forgot password request"""
    
    print("DEBUG: Received data ->>>>>>>>>", data)  # Debug print

    if not isinstance(data, dict):  # Ensure data is a dictionary
        return "Invalid request data", {}, 400  

    email = data.get("email")
    
    if not email:
        print("DEBUG: Missing email in request")
        return "Email is required", {}, 404 

    users = mongo_helper.read_collection(USER_COLLECTION)
    user_data = users.find_one({"email": email})

    if not user_data or user_data.get("role") != "admin":
        return "You don't have access. Please contact the Admin to reset your password.", {}, 403

    passkey = generate_passkey()
    print("DEBUG: Generated Passkey ->", passkey)

    expiry_time = datetime.utcnow() + timedelta(minutes=10)
    users.update_one(
        {"email": email},
        {"$set": {"reset_passkey": passkey, "passkey_expiry": expiry_time}}
    )

    # Call send_passkey_mail_util only once
    return send_passkey_mail_util({"email": email, "passkey": passkey})

def reset_password_util(data):
    email = data.get("email")
    passkey = data.get("passkey")
    new_password = data.get("new_password")
    confirm_password = data.get("confirm_password")

    print("DEBUG: Received data ->>>>>>>>>", data)  # Debug print

    if not email:
        return "Email not provided", {}, 401 

    if not all([email, passkey, new_password, confirm_password]):
        return "Missing data ..", {}, 402
    
    if new_password != confirm_password:
        return "Password Not matched", {}, 403 

    users = mongo_helper.read_collection(USER_COLLECTION)
    user_data = users.find_one({"email": email})

    print("................data", user_data)  # Debugging: Print user data

    if not user_data or user_data.get("role") != "admin":
        return "Operator cannot reset password contact admin", {}, 404

    # Validate passkey and expiration time
    stored_passkey = user_data.get("reset_passkey")
    expiry_time = user_data.get("passkey_expiry")
    
    if not stored_passkey:
        return "Passkey not generated or expired. Request a new passkey.", {}, 405


    print(f"Stored Passkey: {stored_passkey}, Received Passkey: {passkey}")  # Debugging
    print(f"Expiry Time (Stored): {expiry_time}, Current Time: {datetime.utcnow()}")  # Debugging

    if stored_passkey != passkey:
        return "Passkey incorrect", {}, 403

    # Ensure expiry_time is a valid datetime object
    if isinstance(expiry_time, str):
        expiry_time = datetime.fromisoformat(expiry_time)  # Convert from string if needed

    if not expiry_time or datetime.utcnow() > expiry_time:
        return "Your passkey is expired", {}, 404

    # Hash the new password before storing
    hashed_password = generate_password_hash(new_password)
    users.update_one(
        {"email": email},
        {
            "$set": {"password": hashed_password, "invalid_login_count": 0,"account_locked":False},  # Reset invalid login count
            "$unset": {"reset_passkey": "", "passkey_expiry": ""}
         

        }
    )

    # Generate JWT access token
    access_token = create_access_token(identity=email)
    response = {"access_token": access_token}

    return "Password reset successful", response, 200

def login_user(data):
    email = data.get('email') # 	
    password = data.get('password')

    if not email or not password:
        return "Invalid email or password", {"count": 0, "role": None}, 401

    users = mongo_helper.read_collection(USER_COLLECTION)

    # Find user by email
    user_data = users.find_one({"email": email})

    # if not user_data or not check_password_hash(user_data.get('password', ''), password):
    # 	return "Invalid email or password", {}, 401

    # # Generate JWT token
    access_token = create_access_token(identity=email)

    # # Update the user document with the token
    # users.update_one(
    # 	{"email": email},
    # 	{"$set": {"token": access_token}}
    # )
    if not user_data:
        # User not found
        return "Invalid email or password", {"count": 0, "role": None}, 401

    # Check if the account is locked
    if user_data.get("account_locked", False):
        return (
            "Account is locked. Please contact admin.",
            {"count": user_data.get("invalid_login_count", 3), "role": user_data.get("role")},
            403
        )

    # Check password
    if not check_password_hash(user_data.get('password', ''), password):
        # Increment the invalid login count
        invalid_count = user_data.get("invalid_login_count", 0) + 1

        if invalid_count >= 3:
            # Lock the account
            users.update_one(
                {"email": email},
                {
                    "$set": {
                        "account_locked": True,
                        "invalid_login_count": invalid_count,
                        "lock_time": DATE_FORMAT  # Optionally record the lock time
                    }
                }
            )
            return (
                "Account is locked. Please contact admin.",
                {"count": invalid_count, "role": user_data.get("role")},
                403
            )

        # Update invalid login count
        users.update_one(
            {"email": email},
            {
                "$inc": {"invalid_login_count": 1},  # Increment the invalid login count
                "$set": {"last_failed_login": DATE_FORMAT}  # Record the last failed login time
            }
        )
        return "Invalid email or password", {"count": invalid_count, "role": user_data.get("role")}, 401

    login_time = datetime.now()
    logged_time = login_time.strftime("%Y-%m-%d %H:%M:%S ")  # Added space after time

    # Reset invalid login count upon successful login
    users.update_one(
        {"email": email},
        {"$set": {"invalid_login_count": 0, "last_login_time": logged_time}},
          # Store successful login time
    )

    response = {
        "user_id": str(user_data.get("_id")),
        "user":user_data.get("full_name"),
        "role": user_data.get("role"),
        "token": access_token,
        "last_login_time": login_time.isoformat()  # Return login time in response
    }

    return "Success", response, 200

# def logout_user(data):
#     user_id = data.get("user_id")
#     users = mongo_helper.read_collection(USER_COLLECTION)
#     user_data = users.find_one({"_id":ObjectId(user_id)})
#     if user_data is not None:
#         return "Success", {}, 200
#     else:
#         return "Fail", {}, 400
def logout_user(data):
    user_id = data.get("user_id")
    users = mongo_helper.read_collection(USER_COLLECTION)
    user_data = users.find_one({"_id": ObjectId(user_id)})

    if user_data is not None:
        # Get the logout time
        logout_time = datetime.now()
        logged_out_time = logout_time.strftime("%Y-%m-%d %H:%M:%S ")

        # Get last login time from DB
        last_login_str = user_data.get("last_login_time")
        session_duration_readable = None

        if last_login_str:
            try:
                last_login_time = datetime.strptime(last_login_str.strip(), "%Y-%m-%d %H:%M:%S")
                session_duration = logout_time - last_login_time
                total_seconds = int(session_duration.total_seconds())

                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)

                parts = []
                if hours > 0:
                    parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
                if minutes > 0:
                    parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
                if seconds > 0 or (hours == 0 and minutes == 0):
                    parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")

                session_duration_readable = ' '.join(parts)

            except Exception as e:
                print(f"Error parsing login time: {e}")
                session_duration_readable = None

        # Update in DB
        update_fields = {
            "logout_time": logged_out_time,
        }
        if session_duration_readable:
            update_fields["session_duration"] = session_duration_readable

        users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_fields}
        )

        return "Success", {
            "logout_time": logged_out_time,
            "session_duration": session_duration_readable
        }, 200
    else:
        return "Fail", {}, 400
    

def add_user(data):
    """
    {
        "full_name": "anirudh",
        "email": "anirud@factree.ai",
        "phone_number": 9669699669,
        "password": "1334",
        "confirm_password": "1334",
        "role": "operator",
        "user_status": "Active"
    }
    """

    full_name = data.get("full_name")
    email = data.get("email")
    phone_number = data.get("phone_number")
    password = data.get("password")
    confirm_password = data.get("confirm_password")
    role = data.get("role")
    user_status = data.get("user_status", "Active")

    if not email or not password or not confirm_password:
        return "Invalid input", {}, 400

    if password != confirm_password:
        return "Passwords do not match", {}, 400

    # Hash the password
    hashed_password = generate_password_hash(password)

    # Read user collection
    user = mongo_helper.read_collection(USER_COLLECTION)
    user_data = user.find_one({"email": email})
    print("user_data ::: ", user_data)

    if user_status == "Active":
        # Count active users
        active_count = user.count_documents({"user_status": "Active"})

        # Determine the activation status
        if active_count < 5:
            user_status = user_status
        else:
            user_status = "Pending"
    else:
        user_status = "Inactive"

    if user_data is None:
        # Insert new user
        user_id = user.insert_one({
            "email": email,
            "full_name": full_name,
            "password": hashed_password,
            "role": role,
            "phone_number": phone_number,
            "user_status": user_status
        })

        print(user_id)
        message = "User created successfully"
        response = {"user_id": str(user_id.inserted_id), "user_status": user_status}
        status_code = 200
    else:
        message = "User already exists"
        response = {}
        status_code = 400

    return message, response, status_code

# def delete_user(data):
#     email = data.get("email")
#     users = mongo_helper.read_collection(USER_COLLECTION)
#     user_data = users.find_one({"email":email})
#     users.delete_one({"email":email})	
#     return "success", {}, 200


# def update_user(data):
#     """
#     {
#         "email": "email",
#         "password": "new_password",
#         "confirm_password": "new_password",
#         "role": "admin",
#         "full_name": "John Doe",
#         "phone_number" : "1234567890",
#         "user_status": "Active"
#     }
#     """
#     email = data.get("email")
#     password = data.get("password")
#     confirm_password = data.get("confirm_password")
#     role = data.get("role")
#     phone_number = data.get("phone_number")
#     full_name = data.get("full_name")
#     user_status = data.get("user_status", "Active")
    

#     # Validate email
#     if not email:
#         return "Email is required", {}, 400

#     user = mongo_helper.read_collection(USER_COLLECTION)
#     user_data = user.find_one({"email": email})

#     if not user_data:
#         return "User not found", {}, 404

#     update_fields = {"full_name": full_name, "role": role, "user_status": user_status, "phone_number" : phone_number , "account_locked": False,"invalid_login_count": 0}

#     # Update password if provided
#     if password:
#         if password != confirm_password:
#             return "Passwords do not match", {}, 400
#         hashed_password = generate_password_hash(password)
#         update_fields["password"] = hashed_password

#     # Perform the update
#     user.update_one({"_id": user_data["_id"]}, {"$set": update_fields})

#     return "User updated successfully", {}, 200

def delete_user(data):
    email = data.get("email")
    users = mongo_helper.read_collection(USER_COLLECTION)
    user_data = users.find_one({"email":email})
    if user_data:
        full_name = user_data.get("full_name")

        curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
        curr_insp_col_data = curr_insp_col.find_one()
        if curr_insp_col_data:
            running_user = curr_insp_col_data.get("user")
            if running_user == full_name:
                return f"User can not be delete while running the production with the {running_user}", {}, 400


        users.delete_one({"email":email})	
    return "success", {}, 200


def update_user(data):
    """
    {
        "email": "email",
        "password": "new_password",
        "confirm_password": "new_password",
        "role": "admin",
        "full_name": "John Doe",
        "phone_number" : "1234567890",
        "user_status": "Active"
    }
    """
    email = data.get("email")
    password = data.get("password")
    confirm_password = data.get("confirm_password")
    role = data.get("role")
    phone_number = data.get("phone_number")
    full_name = data.get("full_name")
    user_status = data.get("user_status", "Active")
    

    # Validate email
    if not email:
        return "Email is required", {}, 400

    user = mongo_helper.read_collection(USER_COLLECTION)
    user_data = user.find_one({"email": email})

    if not user_data:
        return "User not found", {}, 404
    

    if user_data:
        full_name = user_data.get("full_name")

        curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
        curr_insp_col_data = curr_insp_col.find_one()
        if curr_insp_col_data:
            running_user = curr_insp_col_data.get("user")
            if running_user == full_name:
                return f"User can not be delete while running the production with the {running_user}", {}, 400



    update_fields = {"full_name": full_name, "role": role, "user_status": user_status, "phone_number" : phone_number , "account_locked": False,"invalid_login_count": 0}

    # Update password if provided
    if password:
        if password != confirm_password:
            return "Passwords do not match", {}, 400
        hashed_password = generate_password_hash(password)
        update_fields["password"] = hashed_password

    # Perform the update
    user.update_one({"_id": user_data["_id"]}, {"$set": update_fields})

    return "User updated successfully", {}, 200


########### Parts Utils #################################
def add_part_util(data):
    """
    
        {
        "part_name" : "part1",
        "part_number" : "p001",
        "part_description" : "part_description",
        "model_number" : "m001",
        "expected_cycle_time" : 10.0,
        "part_weight" :   1.0,
        "part_rm_cost" : 11,
        "selling_price" : 100,
        "target_output_per_hour" : 11,
        "defects" : ["FLASH","DUST"],
        "height" : {
            "spections" : 124.5,
            "upper_limit" : 125.0,
            "lower_limit" : 124.0,
            "parameter" : "critical"
        },
        "width" : {
            "spections" : 124.5,
            "upper_limit" : 125.0,
            "lower_limit" : 124.0,
            "parameter" : "critical"
        },
        "diameter" : {
            "specification" : 124.5,
            "upper_limit" : 125.0,
            "lower_limt" : 124.0,
            "parameter" : "critical"
        },

        "target_kpi_ppm" : 3000,
        "target_kpi_oee" : 90.50,
        "target_kpi_yield" : 95.50,
        "target_kpi_availability" : 95.50,
        "target_kpi_product_recall" : 0,
        "target_kpi_defcet" : 1.5,
        "target_kpi_qyality_cost_per_month" : 45,
        "target_kpi_roi" : 3.5,
        "target_kpi_investment" : 3500000

        }
    """
    part_name = data.get("part_name")	
    part_number = data.get("part_number")
    

    parts = mongo_helper.read_collection(PARTS_COLLECTION)
    # print("Parts Collection::::::::::::::::", type(parts), part_name)
    parts_data = parts.find_one({"part_name":part_name,"part_number" : part_number})
    # print("parts_data ::: ", parts_data)

    if parts_data is None:
        parts_id = parts.insert_one(data)

        message = "Part Cretaed successfully"
        response = {"part_id":str(parts_id.inserted_id)} 
        status_code = 200

        return message, response, status_code 
    else:
        message = "Part Alredy Exists"
        response = {} 
        status_code = 400
        return message, response, status_code


# def delete_part_util(data):
#     part_name = data.get("part_name")
#     parts = mongo_helper.read_collection(PARTS_COLLECTION)
#     parts_data = parts.find_one({"part_name":part_name})
#     if parts_data is not None:
#         parts.delete_one({"part_name":part_name})	
        
#         plans = mongo_helper.read_collection(PLANS_COLLECTION)  
#         plans.delete_many({"part_name": part_name})

#         return "deleted  Successfully", {}, 200
#     else:
#         return "Part Not Found", {}, 404
    

# def update_part_util(data):
#     """
#         {
#         "part_name" : "part1",
#         "part_number" : "p001",
#         "part_description" : "part_description",
#         "model_number" : "m001",
#         "expected_cycle_time" : 10.0,
#         "part_weight" :   1.0,
#         "part_rm_cost" : 11,
#         "selling_price" : 100,
#         "target_output_per_hour" : 11,
#         "defect_list" : ["FLASH","DUST"],
#         "height" : {
#             "specification" : 124.5,
#             "upper_limit" : 125.0,
#             "lower_limt" : 124.0,
#             "parameter" : "critical"
#         },
#         "width" : {
#             "specification" : 124.5,
#             "upper_limit" : 125.0,
#             "lower_limt" : 124.0,
#             "parameter" : "critical"
#         },
#         "diameter" : {
#             "specification" : 124.5,
#             "upper_limit" : 125.0,
#             "lower_limt" : 124.0,
#             "parameter" : "critical"
#         },

#         "target_kpi_ppm" : 3000,
#         "target_kpi_oee" : 90.50,
#         "target_kpi_yield" : 95.50,
#         "target_kpi_availability" : 95.50,
#         "target_kpi_product_recall" : 0,
#         "target_kpi_defcet" : 1.5,
#         "target_kpi_quality_cost_per_month" : 45,
#         "target_kpi_roi" : 3.5,
#         "target_kpi_investment" : 3500000

#         }
#     """
    
    
#     part_name = data.get("part_name")	
#     part_number = data.get("part_number")
#     part_description = data.get("part_description")
#     model_number=data.get("model_number")
#     expected_cycle_time = data.get("expected_cycle_time")
#     part_weight = data.get("part_weight")
#     part_rm_cost = data.get("part_rm_cost")
#     selling_price = data.get("selling_price")
#     target_output_per_hour = data.get("target_output_per_hour")
    
#     #Get the defect list 
#     defect_list = data.get("defects",[])
    
#     #Get nested dictionaries
#     height=data.get("height",{})
#     width=data.get("width",{})
#     diameter=data.get("diameter",{})
    
#     staff_cost=data.get("staff_cost_per_day")
#     no_of_staff_shift=data.get("no_of_staff_shift")
#     no_of_shifts=data.get("no_of_shifts")

#     target_kpi_ppm=data.get("target_kpi_ppm")
#     target_kpi_oee=data.get("target_kpi_oee")
#     target_kpi_yield=data.get("target_kpi_yield")
#     target_kpi_availability=data.get("target_kpi_availability")
#     target_kpi_product_recall=data.get("target_kpi_product_recall")
#     target_kpi_defcet=data.get("target_kpi_defcet")
#     target_kpi_quality_cost_per_month=data.get("target_kpi_quality_cost_per_month")
#     target_kpi_roi=data.get("target_kpi_roi")
#     target_kpi_investment=data.get("target_kpi_investment")


#     parts = mongo_helper.read_collection(PARTS_COLLECTION)
#     parts_data = parts.find_one({"part_name":part_name})
#     ("part data ::::",parts_data)
    
#     #Check if the part is already in the database
#     if parts_data:
#         parts_id = parts_data.get("_id")
#         parts.update_one({"_id":parts_id},{"$set":{
#             "part_name":part_name,
#             "part_number":part_number,
#             "part_description" : part_description,
#             "model_number":model_number,
#             "expected_cycle_time":expected_cycle_time,
#             "part_weight":part_weight,
#             "part_rm_cost":part_rm_cost,
#             "selling_price":selling_price,
#             "target_output_per_hour":target_output_per_hour,
#             "defects":defect_list,
#             # Update nested fields

#             "height": height,
#             "width": width,
#             "diameter": diameter,

#             "staff_cost_per_day":staff_cost,
#             "no_of_staff_shift":no_of_staff_shift,
#             "no_of_shifts":no_of_shifts,

#             "target_kpi_ppm":target_kpi_ppm,
#             "target_kpi_oee":target_kpi_oee,
#             "target_kpi_yield":target_kpi_yield,
#             "target_kpi_availability":target_kpi_availability,
#             "target_kpi_product_recall":target_kpi_product_recall,
#             "target_kpi_defcet":target_kpi_defcet,
#             "target_kpi_quality_cost_per_month":target_kpi_quality_cost_per_month,
#             "target_kpi_roi":target_kpi_roi,
#             "target_kpi_investment":target_kpi_investment
#         }})
    
#         return "Successfully updated part",{},200
#     else:
#         return "No part data found", {}, 404



def delete_part_util(data):
    part_name = data.get("part_name")
    parts = mongo_helper.read_collection(PARTS_COLLECTION)
    parts_data = parts.find_one({"part_name":part_name})



    curr_insp = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
    curr_insp_data = curr_insp.find_one()
    if curr_insp_data and  parts_data:
        running_part_name = curr_insp_data.get("part_name")
        running_part_number = curr_insp_data.get("part_number")

        if running_part_number == parts_data.get("part_number") and running_part_name == part_name:
            return "part can not be deleted while ruuning the production", {}, 400
            


    if parts_data is not None:
        parts.delete_one({"part_name":part_name})	
        
        plans = mongo_helper.read_collection(PLANS_COLLECTION)  
        plans.delete_many({"part_name": part_name})

        return "deleted  Successfully", {}, 200
    else:
        return "Part Not Found", {}, 404
    

def update_part_util(data):
    """
        {
        "part_name" : "part1",
        "part_number" : "p001",
        "part_description" : "part_description",
        "model_number" : "m001",
        "expected_cycle_time" : 10.0,
        "part_weight" :   1.0,
        "part_rm_cost" : 11,
        "selling_price" : 100,
        "target_output_per_hour" : 11,
        "defect_list" : ["FLASH","DUST"],
        "height" : {
            "specification" : 124.5,
            "upper_limit" : 125.0,
            "lower_limt" : 124.0,
            "parameter" : "critical"
        },
        "width" : {
            "specification" : 124.5,
            "upper_limit" : 125.0,
            "lower_limt" : 124.0,
            "parameter" : "critical"
        },
        "diameter" : {
            "specification" : 124.5,
            "upper_limit" : 125.0,
            "lower_limt" : 124.0,
            "parameter" : "critical"
        },

        "target_kpi_ppm" : 3000,
        "target_kpi_oee" : 90.50,
        "target_kpi_yield" : 95.50,
        "target_kpi_availability" : 95.50,
        "target_kpi_product_recall" : 0,
        "target_kpi_defcet" : 1.5,
        "target_kpi_quality_cost_per_month" : 45,
        "target_kpi_roi" : 3.5,
        "target_kpi_investment" : 3500000

        }
    """
    
    
    part_name = data.get("part_name")	
    part_number = data.get("part_number")
    part_description = data.get("part_description")
    model_number=data.get("model_number")
    expected_cycle_time = data.get("expected_cycle_time")
    part_weight = data.get("part_weight")
    part_rm_cost = data.get("part_rm_cost")
    selling_price = data.get("selling_price")
    target_output_per_hour = data.get("target_output_per_hour")
    
    #Get the defect list 
    defect_list = data.get("defects",[])
    
    #Get nested dictionaries
    height=data.get("height",{})
    width=data.get("width",{})
    diameter=data.get("diameter",{})
    
    staff_cost=data.get("staff_cost_per_day")
    no_of_staff_shift=data.get("no_of_staff_shift")
    no_of_shifts=data.get("no_of_shifts")

    target_kpi_ppm=data.get("target_kpi_ppm")
    target_kpi_oee=data.get("target_kpi_oee")
    target_kpi_yield=data.get("target_kpi_yield")
    target_kpi_availability=data.get("target_kpi_availability")
    target_kpi_product_recall=data.get("target_kpi_product_recall")
    target_kpi_defcet=data.get("target_kpi_defcet")
    target_kpi_quality_cost_per_month=data.get("target_kpi_quality_cost_per_month")
    target_kpi_roi=data.get("target_kpi_roi")
    target_kpi_investment=data.get("target_kpi_investment")





    curr_insp = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
    curr_insp_data = curr_insp.find_one()
    if curr_insp_data:
        running_part_name = curr_insp_data.get("part_name")
        running_part_number = curr_insp_data.get("part_number")

        if running_part_number == part_number and running_part_name == part_name:
            return "part can not be deleted while ruuning the production", {}, 400
            



    parts = mongo_helper.read_collection(PARTS_COLLECTION)
    parts_data = parts.find_one({"part_name":part_name})
    ("part data ::::",parts_data)
    
    #Check if the part is already in the database
    if parts_data:
        parts_id = parts_data.get("_id")
        parts.update_one({"_id":parts_id},{"$set":{
            "part_name":part_name,
            "part_number":part_number,
            "part_description" : part_description,
            "model_number":model_number,
            "expected_cycle_time":expected_cycle_time,
            "part_weight":part_weight,
            "part_rm_cost":part_rm_cost,
            "selling_price":selling_price,
            "target_output_per_hour":target_output_per_hour,
            "defects":defect_list,
            # Update nested fields

            "height": height,
            "width": width,
            "diameter": diameter,

            "staff_cost_per_day":staff_cost,
            "no_of_staff_shift":no_of_staff_shift,
            "no_of_shifts":no_of_shifts,

            "target_kpi_ppm":target_kpi_ppm,
            "target_kpi_oee":target_kpi_oee,
            "target_kpi_yield":target_kpi_yield,
            "target_kpi_availability":target_kpi_availability,
            "target_kpi_product_recall":target_kpi_product_recall,
            "target_kpi_defcet":target_kpi_defcet,
            "target_kpi_quality_cost_per_month":target_kpi_quality_cost_per_month,
            "target_kpi_roi":target_kpi_roi,
            "target_kpi_investment":target_kpi_investment
        }})
    
        return "Successfully updated part",{},200
    else:
        return "No part data found", {}, 404
    


def get_all_parts_data():
    parts = mongo_helper.read_collection(PARTS_COLLECTION)
    # print("parts----------->",parts)
    parts_data = [i for i in parts.find()]
    # print("parts_data ----------->",parts_data)

    return "Success", {"data":parts_data}, 200

######  Production Plan Utils #################################
# def add_production_plan_util(data):
# 	"""payload"""
# 	{
# 		"part_name":"part 1",
# 		"part_number":"p001",
# 		"shift":"A",
# 		"batch_number ":"b001",
# 		"expected_output":"1000",
# 		"Production_order_number(PO)":"ARPON132",
# 		"Production_order_quantity":"1800",
# 		"Operator":"operator 1",
# 		# "Inspector":"inspector 1",
# 		"production_date": "2025-01-20T17:54:04" 
# 	}

# 	part_name = data.get("part_name")
# 	part_number= data.get("part_number")
# 	production_date=data.get("production_date")
# 	operator = data.get("operator")
# 	shift = data.get("shift")

    
# 	plans= mongo_helper.read_collection(PLANS_COLLECTION)
# 	plans_data = plans.find_one({"operator":operator,"shift":shift})
# 	print("plans_data::: ", plans_data)
# 	if plans_data is None:
# 		data["production_date"] = production_date
# 		plans_id = plans.insert_one(data)
# 		print("plans_id::: ", plans_id)
# 		message="Plan created successfully"
# 		response={"plans_id":str(plans_id.inserted_id)}	
# 		status_code =200
# 	else:
# 		message="Plan already exists"
# 		response={}
# 		status_code=400
# 	return message, response, status_code

def add_production_plan_util(data):
    """payload"""
    {
        "part_name":"part 1",
        "part_number":"p001",
        "shift":"A",
        "batch_number":"b001",
        "expected_output":"1000",
        "production_order_number(PO)":"ARPON132",
        "production_order_quantity":"1800",
        "operator":"operator 1",
        "production_date": "2025-01-20T17:54:04" 
    }

    print(data)

    part_name = data.get("part_name")
    part_number= data.get("part_number")
    production_date=data.get("production_date")
    operator = data.get("operator")
    shift = data.get("shift")
    print(shift,"shift")
    # shift_time_ranges = {
    # 	"shift a": {"start_time": "06:00:00", "end_time": "13:59:59"},
    # 	"shift b": {"start_time": "14:00:00", "end_time": "21:59:59"},
    # 	"shift c": {"start_time": "22:00:00", "end_time": "05:59:59"}
    # }
    shift_time_ranges = SHIFTS


    
    # Retrieve the corresponding time range
    shift_times = shift_time_ranges[shift]
    start_time = shift_times["start_time"]
    end_time = shift_times["end_time"]


    
    plans= mongo_helper.read_collection(PLANS_COLLECTION)
    plans_data = plans.find_one({"operator":operator,"shift":shift,"production_date":production_date})
    print("plans_data::: ", plans_data)
    if plans_data is None:
        data["production_date"] = production_date
        data["start_time"] =start_time
        data["end_time"]= end_time
        data["status"] = "Not Started "
        plans_id = plans.insert_one(data)
        print("plans_id::: ", plans_id)
        message="Plan created successfully"
        response={"plans_id":str(plans_id.inserted_id)}	
        status_code =200
    else:
        message="Plan already exists"
        response={}
        status_code=400
    return message, response, status_code


# def delete_production_plan_util(data):
#     part_name = data.get("part_name")

#     # if not part_name:
#     #     return "Bad Request: 'part_name' is required", {}, 400
#     plans = mongo_helper.read_collection(PLANS_COLLECTION)
#     plans_data = plans.find_one({"part_name": part_name})
#     if plans_data is not None:
#         plans.delete_one({"part_name": part_name})
#         return "Deleted Plan Successfully", {}, 200
#     else:
#         return "Part Not Found", {}, 404


# def update_production_plan_util(data):
# 	"""Update production plan"""
# 	{
# 		"part_id":"654574554755888585",
# 		"part_name":"part 1",
# 		"part_number":"p001",
# 		"shift":"A",
# 		"batch_number ":"b001",
# 		"expected_output":"1000",
# 		"production_order_quantity":"1800",
# 		"operator":"operator 1",
# 		"production_date": "2025-01-20T17:54:04" 
# 	}
# 	print(",,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,",data)
# 	part_id = data.get("part_id")
# 	part_name = data.get("part_name")
# 	part_number= data.get("part_number")
# 	shift=data.get("shift")
# 	batch_number=data.get("batch_number")
# 	expected_output=data.get("expected_output")
# 	production_order_quantity=data.get("production_order_quantity")
# 	operator=data.get("operator")
# 	production_date=data.get("production_date")
# 	shift_time_ranges = {
# 		"shift a": {"start_time": "06:00:00", "end_time": "13:59:59"},
# 		"shift b": {"start_time": "14:00:00", "end_time": "21:59:59"},
# 		"shift c": {"start_time": "22:00:00", "end_time": "05:59:59"}
# 	}

# 	# Check if the provided shift is valid
# 	if shift.lower() not in shift_time_ranges:
# 		return "Invalid shift value provided. Please use 'shift a', 'shift b', or 'shift c'.", {"shift": shift}, 400

# 	# Retrieve the corresponding time range
# 	shift_times = shift_time_ranges[shift.lower()]
# 	start_time = shift_times["start_time"]
# 	end_time = shift_times["end_time"]

    
    
# 	plans = mongo_helper.read_collection(PLANS_COLLECTION)
# 	plans_data = plans.find_one({"_id": part_id})
# 	print("plans data",plans_data)
# 	if plans_data is not None:
# 		plans.update_one({"_id": part_id}, {"$set": 
# 			{
# 			"part_name" : part_name,
# 			"part_number":part_number,
# 			"shift": shift,
# 			"start_time" :start_time,
# 			"end_time": end_time, 
# 			"batch_number": batch_number, 
# 			"expected_output": expected_output, 
# 			"production_order_quantity": production_order_quantity, 
# 			"operator": operator, 
# 			"production_date": production_date}
# 		})
# 		return "Updated Plan Successfully", {}, 200
# 	else:
# 		return "Part Not Found", {}, 404

# def update_production_plan_util(data):
#     """Update production plan"""
#     {
#         "part_name":"part 1",
#         "part_number":"p001",
#         "shift":"A",
#         "batch_number ":"b001",
#         "expected_output":"1000",
#         "production_order_quantity":"1800",
#         "operator":"operator 1",
#         "production_date": "2025-01-20T17:54:04" 
#     }

#     print("payload getting from frond end------------------->",data)
#     part_id_string = data.get("part_id")
#     part_id = ObjectId(part_id_string)
#     part_name = data.get("part_name")
#     part_number= data.get("part_number")
#     shift=data.get("shift")
#     # shift_time_ranges = {
#     # 	"shift a": {"start_time": "06:00:00", "end_time": "14:59:59"},
#     # 	"shift b": {"start_time": "14:00:00", "end_time": "22:59:59"},
#     # 	"shift c": {"start_time": "22:00:00", "end_time": "06:59:59"}
#     # }

#     shift_time_ranges = SHIFTS
#     batch_number=data.get("batch_number")
#     production_order_number = data.get("production_order_number")
#     expected_output=data.get("expected_output")
#     production_order_quantity=data.get("production_order_quantity")
#     operator=data.get("operator")
#     production_date=data.get("production_date")

#     # Retrieve the corresponding time range
#     shift_times = shift_time_ranges[shift]
#     start_time = shift_times["start_time"]
#     end_time = shift_times["end_time"]

#     plans = mongo_helper.read_collection(PLANS_COLLECTION)
#     plans_data = plans.find_one({"_id": part_id})
#     print("plans dataaaaaaa",plans_data)
#     if plans_data is not None:
#         plans.update_one({"_id": part_id}, {"$set": 
#             {
#             "part_name" : part_name,
#             "part_number":part_number,
#             "shift": shift, 
#             "start_time": start_time,
#             "end_time": end_time,
#             "batch_number": batch_number, 
#             "expected_output": expected_output, 
#             "start_time":start_time,
#             "end_time":end_time,
#             "production_order_quantity": production_order_quantity, 
#             "operator": operator, 
#             "production_date": production_date,
#             "production_order_number":production_order_number}
            
#         })
#         return "Updated Plan Successfully", {}, 200
#     else:
#         return "Part Not Found", {}, 404
    


# def get_all_production_plans_util():
#     """Get all production plans"""
#     plans=mongo_helper.read_collection(PLANS_COLLECTION)
#     print("plans----------->",plans)
#     plans_data = [i for i in plans.find().sort("_id",-1)]
#     print("plans_data ----------->",plans_data)


  


#     return "Success", {"data":plans_data}, 200
#     # return "Success", {"data":updated_plans_data}, 200

def check_running_production(part_name,part_number,user):
    curr = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
    curr_data = curr.find_one()
    is_running = False
    if curr_data:
        if part_name == curr_data.get("part_name")  or part_number == curr_data.get("part_number") or user == curr_data.get("user"):
            is_running = True
    return is_running

def delete_production_plan_util(data):

    part_id = data.get("part_name")

    # if not part_name:
    #     return "Bad Request: 'part_name' is required", {}, 400
    plans = mongo_helper.read_collection(PLANS_COLLECTION)
    plans_data = plans.find_one({"_id":bson.ObjectId(part_id) })
    print("plans_data",plans_data,"plans_data")
    part_name = plans_data.get("part_name")
    part_number= plans_data.get("part_number")
    operator=plans_data.get("operator")
    is_running = check_running_production(part_name,part_number,operator)
    if is_running is True:
        return " Plan is running ...! You can not Delete this plan", {}, 400

    if plans_data is not None:
        plans.delete_one({"_id": ObjectId(part_id)})
        return "Deleted Plan Successfully", {}, 200
    else:
        return "Part Not Found", {}, 404



def update_production_plan_util(data):
    """Update production plan"""
    {
        "part_name":"part 1",
        "part_number":"p001",
        "shift":"A",
        "batch_number ":"b001",
        "expected_output":"1000",
        "production_order_quantity":"1800",
        "operator":"operator 1",
        "production_date": "2025-01-20T17:54:04" 
    }

    print("payload getting from frond end------------------->",data)
    part_id_string = data.get("part_id")
    part_id = ObjectId(part_id_string)
    part_name = data.get("part_name")
    part_number= data.get("part_number")
    shift=data.get("shift")


    shift_time_ranges = SHIFTS
    batch_number=data.get("batch_number")
    production_order_number = data.get("production_order_number")
    expected_output=data.get("expected_output")
    production_order_quantity=data.get("production_order_quantity")
    operator=data.get("operator")
    production_date=data.get("production_date")

    # Retrieve the corresponding time range
    shift_times = shift_time_ranges[shift]
    start_time = shift_times["start_time"]
    end_time = shift_times["end_time"]


    is_running = check_running_production(part_name,part_number,operator)
    if is_running is True:
        return " Plan is running ...! You can not Update this plan", {}, 400


    plans = mongo_helper.read_collection(PLANS_COLLECTION)
    plans_data = plans.find_one({"_id": part_id})
    print("plans dataaaaaaa",plans_data)
    if plans_data is not None:
        plans.update_one({"_id": part_id}, {"$set": 
            {
            "part_name" : part_name,
            "part_number":part_number,
            "shift": shift, 
            "start_time": start_time,
            "end_time": end_time,
            "batch_number": batch_number, 
            "expected_output": expected_output, 
            "start_time":start_time,
            "end_time":end_time,
            "production_order_quantity": production_order_quantity, 
            "operator": operator, 
            "production_date": production_date,
            "production_order_number":production_order_number}
            
        })
        return "Updated Plan Successfully", {}, 200
    else:
        return "Part Not Found", {}, 404
    


def get_all_production_plans_util():
    """Get all production plans"""
    plans=mongo_helper.read_collection(PLANS_COLLECTION)
    print("plans----------->",plans)
    plans_data = [i for i in plans.find().sort("_id",-1)]
    print("plans_data ----------->",plans_data)

    return "Success", {"data":plans_data}, 200

########### Inspection Utils #################################

def save_inspection_per_image_util(data):
    """
        
    """
    predictions = data.get("predictions")
    inspection_id = data.get("inspection_id")

    ## save predicted image
    predicted_image_key = data.get("predicted_image_key")
    predicted_image = redis_helper.pull_data(predicted_image_key)
    save_predicted_path = os.path.join("bucket",datetime.now().strftime("%Y-%m-%d"),"predicted",str(inspection_id))
    os.makedirs(save_predicted_path,exist_ok=True)
    save_predicted_image_path = os.path.join(save_predicted_path,str(bson.ObjectId())+"_predicted.jpg")
    cv2.imwrite(save_predicted_image_path,predicted_image)

    ## save input image
    input_image_key = data.get("input_image_key")
    input_image = redis_helper.pull_data(input_image_key)	
    save_input_path = os.path.join("bucket",datetime.now().strftime("%Y-%m-%d"),"input",str(inspection_id))
    os.makedirs(save_input_path,exist_ok=True)
    save_input_image_path = os.path.join(save_input_path,str(bson.ObjectId())+"_input.jpg")
    cv2.imwrite(save_input_image_path,input_image)



    inspection = mongo_helper.read_collection(str(inspection_id))
    inserted_id = inspection.insert_one(
        {
            "time_stamp": datetime.now().strftime(DATE_FORMAT),
            "predictions" : predictions,
            "inspection_id": str(inspection_id),
            "input_image" : save_input_image_path.replace("bucket","http://localhost:3307"),
            "predicted_image" : save_predicted_image_path.replace("bucket","http://localhost:3307"),
            "consolidated":False

        }
    )
    inserted_id = inserted_id.inserted_id
    return "Data Inserted", {"inserted_id":inserted_id}, 200

def convert_list_to_dict(data):
    converted_dict = {}
    for i in set(data):
        converted_dict[i] = data.count(i)
    return converted_dict



def get_inspection_status(prediction_list):
    with open('bl_config.json', 'r') as file:
        json_data = json.load(file)
    defect_list = json_data.get("defect_list")
    feature_dict = json_data.get("feature_dict")

    status = None
    defects = []
    features = []

    ## defects logic
    for prediction in prediction_list:
        if prediction in defect_list:
            defects.append(prediction)
            
    ## featue logic
    prediction_dict = convert_list_to_dict(prediction_list)

    print("prediction dict--------------->", prediction_dict)
    for feature, feature_count in feature_dict.items():
        for f_inf, fc_inf in prediction_dict.items():
            if feature == f_inf and feature_count == fc_inf:
                pass
        else:
            features.append(feature)
    ## status logic
    if defects or features:
        status = "NOK"
    else:
        status = "OK"
    
    return status, defects, features


def get_part_data(part_name, part_number):
    parts_col = mongo_helper.read_collection(PARTS_COLLECTION)
    parts_col_data = parts_col.find_one({"part_name":part_name,"part_number":part_number})
    return parts_col_data


def get_inspection_status_updated(part_name, part_number,prediction_list,predicted_height=0,predicted_width=0,predicted_diameter=0):
    print(f"part name :: {part_name}, part number :: {part_number}")
    parts_data = get_part_data(part_name,part_number)
    print(f"parts data :: {parts_data}")
    defect_list = parts_data.get("defects")
    height_obj = parts_data.get("height")
    width_obj = parts_data.get("width")
    diameter_obj = parts_data.get("diameter")


    predicted_height = float(predicted_height)
    perdicted_width = float(predicted_width)
    predicted_diameter = float(predicted_diameter)


    # print("part_data ---->>>",parts_data)
    # print('height-obj',height_obj,type(height_obj))
    print(f"predicted_height :: {predicted_height},  perdicted_width :: {perdicted_width}, predicted_diameter :: {predicted_diameter}")
    print(f"height_obj :: {height_obj},  width_obj :: {width_obj}, diameter_obj :: {diameter_obj}")
    
    
    status = None
    defects_found = []

    ## check defects logic 
    for prediction in prediction_list:
        if prediction in defect_list:
            defects_found.append(prediction)
    
    
    height_lower_limit = float(height_obj["lowerlimit"])
    height_upper_limit = float(height_obj["upperlimit"])
    
    width_lower_limit = float(height_obj["lowerlimit"])
    width_upper_limit = float(height_obj["upperlimit"])
    
    diameter_lower_limit = float(height_obj["lowerlimit"])
    diameter_upper_limit = float(height_obj["upperlimit"])

    print(f"height_lower_limit :: {height_lower_limit}")


    if height_lower_limit <= predicted_height <= height_upper_limit:
        print("inp is within the range.")
    else:
        defects_found.append("Height Mis-Match")
        print("inp is outside the range.")


    if width_lower_limit <= predicted_width <= width_upper_limit:
        print("inp is within the range.")
    else:
        defects_found.append("Width Mis-Match")
        print("inp is outside the range.")
  
    if diameter_lower_limit <= predicted_diameter <= diameter_upper_limit:
        print("inp is within the range.")
    else:
        defects_found.append("Diameter Mis-Match")
        print("inp is outside the range.")
    
    if defects_found:
        status = "NOK"
    else:
        status = "OK"
    
    parts_data["defects_found"] = convert_list_to_dict(defects_found)
    parts_data["status"] = status
    parts_data["predicted_height"] = predicted_height
    parts_data["predicted_width"] = predicted_width 
    parts_data["predicted_diameter"] = predicted_diameter

    return parts_data



def save_inspection_results_util(data):
    inspection_id = data.get("inspection_id")
    prediction_list = data.get("prediction_list")
    predicted_images = data.get("predicted_images")
    input_images = data.get("input_images")
    predicted_height = data.get("predicted_height")
    predicted_width = data.get("predicted_width")
    predicted_diameter = data.get("predicted_diameter")
    cycle_time = data.get("cycle_time")

    curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
    curr_insp_col_data = curr_insp_col.find_one()
    part_name = curr_insp_col_data.get("part_name")
    part_number = curr_insp_col_data.get("part_number")
    user = curr_insp_col_data.get("user")
    batch_name = curr_insp_col_data.get("batch_number")
    shift = curr_insp_col_data.get("shift")


    resp_obj = get_inspection_status_updated(part_name,part_number,prediction_list,predicted_height,predicted_width,predicted_diameter)
    resp_obj["inspection_id"] = str(inspection_id)
    resp_obj["time_stamp"] = datetime.now().strftime(DATE_FORMAT)
    resp_obj["predicted_images"] = predicted_images
    resp_obj["prediction_list"] = prediction_list
    resp_obj["input_images"] = input_images
    resp_obj["shift"] = shift
    resp_obj["user"] = user
    resp_obj["batch_name"] = batch_name
    resp_obj["cycle_time"] = cycle_time

    del resp_obj["_id"]


    

    log_col = mongo_helper.read_collection(str(inspection_id)+"_logs")
    log_col.insert_one(resp_obj)	
    return "success",{},200


    

# def save_overall_inspection_util(data):
#     inspection_id = data.get("inspection_id")
#     if not inspection_id:
#         return "Please Provide Inspection ID", {}, 400
#     predicted_height = data.get("predicted_height",0)
#     predicted_width = data.get("predicted_width",0)
#     predicted_diameter = data.get("predicted_diameter",0)

    
#     inspection_col = mongo_helper.read_collection(str(inspection_id))
#     inspection_data = inspection_col.find({"consolidated":False})

#     prediction_list = []
#     predicted_images = []
#     input_images = []
#     for i in inspection_data:
#         predictions = i.get("predictions")
#         predicted_image = i.get("predicted_image")
#         input_image = i.get("input_image")
#         prediction_list.extend(predictions)
#         predicted_images.append(predicted_image)
#         input_images.append(input_image)
#         i["consolidated"] = True
#         inspection_col.update_one({"_id":i["_id"]},{"$set":i})


    
#     curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
#     curr_insp_col_data = curr_insp_col.find_one()
#     part_name = curr_insp_col_data.get("part_name")
#     part_number = curr_insp_col_data.get("part_number")
#     user = curr_insp_col_data.get("user")
#     batch_name = curr_insp_col_data.get("batch_number")
#     shift = curr_insp_col_data.get("shift")
#     prediction_list.extend(predictions)
 
#     date_part = datetime.now().strftime("%Y-%m-%d")
#     time_part = datetime.now().strftime("%H:%M:%S")

 
#     resp_obj = get_inspection_status_updated(part_name,part_number,prediction_list,predicted_height,predicted_width,predicted_diameter,prediction_list)
#     resp_obj["inspection_id"] = str(inspection_id)
#     resp_obj["time_stamp"] = datetime.now().strftime(DATE_FORMAT)
#     resp_obj["date_part"]= date_part
#     resp_obj["time_part"] = time_part
#     resp_obj["predicted_images"] = predicted_images
#     resp_obj["input_images"] = input_images
#     resp_obj["shift"] = shift
#     resp_obj["user"] = user
#     resp_obj["batch_name"] = batch_name

#     del resp_obj["_id"]


#     print("""......Time in secs""", time_part)
#     print("...date format", date_part)

#     log_col = mongo_helper.read_collection(str(inspection_id)+"_logs")
#     log_col.insert_one(resp_obj)	
 
#     return "Success", {}, 200

def save_overall_inspection_util(data):
    inspection_id = data.get("inspection_id")
    if not inspection_id:
        return "Please Provide Inspection ID", {}, 400
    predicted_height = data.get("predicted_height",0)
    predicted_width = data.get("predicted_width",0)
    predicted_diameter = data.get("predicted_diameter",0)

    
    inspection_col = mongo_helper.read_collection(str(inspection_id))
    inspection_data = inspection_col.find({"consolidated":False})

    prediction_list = []
    predicted_images = []
    input_images = []
    for i in inspection_data:
        predictions = i.get("predictions")
        predicted_image = i.get("predicted_image")
        input_image = i.get("input_image")
        prediction_list.extend(predictions)
        predicted_images.append(predicted_image)
        input_images.append(input_image)
        i["consolidated"] = True
        inspection_col.update_one({"_id":i["_id"]},{"$set":i})


    
    curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
    curr_insp_col_data = curr_insp_col.find_one()
    part_name = curr_insp_col_data.get("part_name")
    part_number = curr_insp_col_data.get("part_number")
    user = curr_insp_col_data.get("user")
    batch_name = curr_insp_col_data.get("batch_number")
    shift = curr_insp_col_data.get("shift")
    prediction_list.extend(predictions)
 
    date_part = datetime.now().strftime("%Y-%m-%d")
    time_part = datetime.now().strftime("%H:%M:%S")

 
    resp_obj = get_inspection_status_updated(part_name,part_number,prediction_list,predicted_height,predicted_width,predicted_diameter,prediction_list)
    resp_obj["inspection_id"] = str(inspection_id)
    resp_obj["time_stamp"] = datetime.now().strftime(DATE_FORMAT)
    resp_obj["date_part"]= date_part
    resp_obj["time_part"] = time_part
    resp_obj["predicted_images"] = predicted_images
    resp_obj["input_images"] = input_images
    resp_obj["shift"] = shift
    resp_obj["user"] = user
    resp_obj["batch_name"] = batch_name

    del resp_obj["_id"]


    print("""......Time in secs""", time_part)
    print("...date format", date_part)

    log_col = mongo_helper.read_collection(str(inspection_id)+"_logs")
    log_col.insert_one(resp_obj)	
 
    return "Success", {}, 200


def inspect_util(data):
    stage = data.get("stage")

    redis_helper.push_data("inspection_trigger",stage)
    return "Triggered", {}, 200
    
# def start_process_util(data):
# 	part_name = data.get("part_name",None)
# 	if part_name is None:
# 		return "Please provide part name ", {"part_name":"part_name"},400

# 	batch_name = data.get("batch_name")
# 	if batch_name is None:
# 		return "Please provide batch id ", {"batch_name":"batch_name"},400
# 	part_number = data.get("part_number")
# 	if part_number is None:
# 		return "Please provide part number ", {"part_number":"part_number"},400
 
# 	user = data.get("user", None)
# 	if user is None:
# 		return "Please provide Logged in user",{"user":"user"}, 400


# 	insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)
# 	insreted_obj = insp_col.insert_one({
# 		"part_name" : part_name,
# 		"batch_name" : batch_name,
#   		"part_number":part_number,
# 		"user" : user,
# 		"started_at" : datetime.now().strftime(DATE_FORMAT)

# 	})
    
# 	inspection_id = str(insreted_obj.inserted_id)

# 	curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
# 	curr_insp_col.insert_one({
# 		"part_name" : part_name,
# 		"batch_name" : batch_name,
#   		"part_number":part_number,
# 		"user" : user,
# 		"started_at" : datetime.now().strftime(DATE_FORMAT),
# 		"current_inspection_id" : inspection_id

# 	})
    
    

# 	parts_col = mongo_helper.read_collection(PARTS_COLLECTION)
# 	parts_col_data = parts_col.find_one({
# 		"part_name" : part_name,
# 		"part_number" : part_number
# 	})
# 	defects = parts_col_data.get("defects")

# 	requests.post("http://localhost:9000/load_model",json={"defects":defects})

# 	return "Success", {"inspection_id":inspection_id}, 200

# def start_process_util(data):
#     # part_name = data.get("part_name",None)
#     # if part_name is None:
#     # 	return "Please provide part name ", {"part_name":"part_name"},400

#     # batch_name = data.get("batch_name")
#     # if batch_name is None:
#     # 	return "Please provide batch id ", {"batch_name":"batch_name"},400
#     # part_number = data.get("part_number")
#     # if part_number is None:
#     # 	return "Please provide part number ", {"part_number":"part_number"},400
#     print(data,"payload")

#     user = data.get("user", None)

#     if user is None:
#         return "Please provide Logged in user",{"user":"user"}, 400

    
#     plans_col = mongo_helper.read_collection(PLANS_COLLECTION)


#     shift_time_ranges = SHIFTS
    
#     def get_current_shift_and_date():
#         current_datetime = datetime.now()
#         current_time = current_datetime.time()
#         current_date = current_datetime.date()

#         for shift, times in shift_time_ranges.items():
#             start_time = datetime.strptime(times["start_time"], "%H:%M:%S").time()
#             end_time = datetime.strptime(times["end_time"], "%H:%M:%S").time()

#             if start_time <= end_time:  # Regular shift range
#                 if start_time <= current_time <= end_time:
#                     return shift, current_date
#             else:  # Overnight shift range
#                 if current_time >= start_time or current_time <= end_time:
#                     # If the shift is overnight and it's after midnight, adjust the date
#                     if current_time <= end_time:
#                         current_date = current_date.replace(day=current_date.day - 1)
#                     return shift, current_date

#         return "Unknown Shift", current_date

#     current_shift, current_date = get_current_shift_and_date()
    
#     print(f"current shift :: {current_shift}, current_date :: {current_date}, type of date :: {type(current_date)}")

#     # print(plans_col)
#     operator_data = plans_col.find_one({"operator": user,"shift":current_shift,"production_date":str(current_date)})


#     print("operator_data ::: ",operator_data)
#     # Check if the operator is the same as the user
#     if operator_data is  None:
#         return "Dont have any Production Plan Please contact Admin" ,{}, 400

#     if operator_data.get("operator") != user:
#         return "Dont have any Production Plan Please contact Admin" ,{}, 400

#         # Check for a valid production plan for the user on the current date
#     if user == operator_data.get("operator"):
#         # current_time = datetime.now().strftime("%H:%M:%S")
#         start_time_str = operator_data.get("start_time")
#         end_time_str = operator_data.get("end_time")	

#         start_time = datetime.strptime(start_time_str, "%H:%M:%S")
#         end_time = datetime.strptime(end_time_str, "%H:%M:%S")

            
#         # Get the current time (as a datetime object)
#         current_time = datetime.now().strftime("%H:%M:%S")
#         current_time = datetime.strptime(current_time, "%H:%M:%S")  # Convert current time to datetime object

#         # Print the times for debugging
#         print(f"start time :: {start_time} ,type {type(start_time)}, :end time  :::: {type(end_time)}, type :: {end_time}, current time :: {current_time}. type :: {type(current_time)}")

#         # Check if current_time is within the range (handling the midnight crossing case)
#         if not (start_time <= current_time <= end_time or (start_time > end_time and (current_time >= start_time or current_time <= end_time))):
#             # Handle case when current_time is within the range
#             return "Don't have any Production Plan. Please contact Admin", {}, 400
        
#         else:
#             part_name=operator_data.get("part_name")
#             part_number=operator_data.get("part_number")
#             batch_number=operator_data.get("batch_number")
#             shift = operator_data.get("shift")
#             insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)
#             insreted_obj = insp_col.insert_one({
#                 "part_name" : part_name,
#                 "batch_name" : batch_number,
#                 "part_number":part_number,
#                 "user" : user,
#                 "started_at" : datetime.now().strftime(DATE_FORMAT),
#                 "shift":shift

#             })
#             inspection_id = str(insreted_obj.inserted_id)
#             print("par",part_number,part_name,batch_number,inspection_id)


#             curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
#             curr_insp_col.insert_one({
#                 "part_name" : part_name,
#                 "batch_number" : batch_number,
#                 "part_number":part_number,
#                 "user" : user,
#                 "started_at" : datetime.now().strftime(DATE_FORMAT),
#                 "current_inspection_id" : inspection_id,
#                 "shift":shift,
#                 "is_running":True
#             })
            
#             redis_helper.push_data("inspection_id",inspection_id)
#             redis_helper.push_data("part_name",part_name)
#             redis_helper.push_data("part_number",part_number)

            
#             return "Success", {"inspection_id":inspection_id}, 200
        


# def start_process_util(data):
   


#     print(data,"payload")

#     user = data.get("user", None)

#     if user is None:
#         return "Please provide Logged in user",{"user":"user"}, 400

    
#     plans_col = mongo_helper.read_collection(PLANS_COLLECTION)


#     shift_time_ranges = SHIFTS
    
#     def get_current_shift_and_date():
#         current_datetime = datetime.now()
#         current_time = current_datetime.time()
#         current_date = current_datetime.date()

#         for shift, times in shift_time_ranges.items():
#             start_time = datetime.strptime(times["start_time"], "%H:%M:%S").time()
#             end_time = datetime.strptime(times["end_time"], "%H:%M:%S").time()

#             if start_time <= end_time:  # Regular shift range
#                 if start_time <= current_time <= end_time:
#                     return shift, current_date
#             else:  # Overnight shift range
#                 if current_time >= start_time or current_time <= end_time:
#                     # If the shift is overnight and it's after midnight, adjust the date
#                     if current_time <= end_time:
#                         current_date = current_date.replace(day=current_date.day - 1)
#                     return shift, current_date

#         return "Unknown Shift", current_date

#     current_shift, current_date = get_current_shift_and_date()
    
#     print(f"current shift :: {current_shift}, current_date :: {current_date}, type of date :: {type(current_date)}")

#     # print(plans_col)
#     operator_data = plans_col.find_one({"operator": user,"shift":current_shift,"production_date":str(current_date)})


#     print("operator_data ::: ",operator_data)
#     # Check if the operator is the same as the user
#     if operator_data is  None:
#         return "Dont have any Production Plan Please contact Admin" ,{}, 400

#     if operator_data.get("operator") != user:
#         return "Dont have any Production Plan Please contact Admin" ,{}, 400

#         # Check for a valid production plan for the user on the current date
#     if user == operator_data.get("operator"):
#         # current_time = datetime.now().strftime("%H:%M:%S")
#         start_time_str = operator_data.get("start_time")
#         end_time_str = operator_data.get("end_time")	

#         start_time = datetime.strptime(start_time_str, "%H:%M:%S")
#         end_time = datetime.strptime(end_time_str, "%H:%M:%S")

            
#         # Get the current time (as a datetime object)
#         current_time = datetime.now().strftime("%H:%M:%S")
#         current_time = datetime.strptime(current_time, "%H:%M:%S")  # Convert current time to datetime object

#         # Print the times for debugging
#         print(f"start time :: {start_time} ,type {type(start_time)}, :end time  :::: {type(end_time)}, type :: {end_time}, current time :: {current_time}. type :: {type(current_time)}")

#         # Check if current_time is within the range (handling the midnight crossing case)
#         if not (start_time <= current_time <= end_time or (start_time > end_time and (current_time >= start_time or current_time <= end_time))):
#             # Handle case when current_time is within the range
#             return "Don't have any Production Plan. Please contact Admin", {}, 400
        
#         else:
#             part_name=operator_data.get("part_name")
#             part_number=operator_data.get("part_number")
#             batch_number=operator_data.get("batch_number")
#             shift = operator_data.get("shift")
#             insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)
#             insreted_obj = insp_col.insert_one({
#                 "part_name" : part_name,
#                 "batch_name" : batch_number,
#                 "part_number":part_number,
#                 "user" : user,
#                 "started_at" : datetime.now().strftime(DATE_FORMAT),
#                 "shift":shift

#             })
#             inspection_id = str(insreted_obj.inserted_id)
#             print("par",part_number,part_name,batch_number,inspection_id)


#             curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
#             started_at = datetime.now().strftime(DATE_FORMAT)
#             curr_insp_col.insert_one({
#                 "part_name" : part_name,
#                 "batch_number" : batch_number,
#                 "part_number":part_number,
#                 "user" : user,
#                 "started_at" : started_at ,
#                 "current_inspection_id" : inspection_id,
#                 "shift":shift,
#                 "is_running":True
#             })


#             plans_col = mongo_helper.read_collection(PLANS_COLLECTION)
#             plans_col_data = plans_col.find_one({"part_name":part_name,"part_number":part_number,"operator":user,"shift":shift})
#             print("Plan :::",plans_col_data)
#             if plans_col_data:
#                 production_date = plans_col_data.get("production_date")

#                 if production_date in started_at:

#                     plans_col_data["status"] = "Running"
#                     plans_col.update_one({"_id":plans_col_data.get("_id")},{"$set":plans_col_data})
                
            
#             redis_helper.push_data("inspection_id",inspection_id)
#             redis_helper.push_data("part_name",part_name)
#             redis_helper.push_data("part_number",part_number)

            
#             return "Success", {"inspection_id":inspection_id}, 200



def start_process_util(data):
    # part_name = data.get("part_name",None)
    # if part_name is None:
    # 	return "Please provide part name ", {"part_name":"part_name"},400

    # batch_name = data.get("batch_name")
    # if batch_name is None:
    # 	return "Please provide batch id ", {"batch_name":"batch_name"},400
    # part_number = data.get("part_number")
    # if part_number is None:
    # 	return "Please provide part number ", {"part_number":"part_number"},400




    print(data,"payload")

    user = data.get("user", None)

    if user is None:
        return "Please provide Logged in user",{"user":"user"}, 400

    
    plans_col = mongo_helper.read_collection(PLANS_COLLECTION)


    shift_time_ranges = SHIFTS
    
    def get_current_shift_and_date():
        current_datetime = datetime.now()
        current_time = current_datetime.time()
        current_date = current_datetime.date()

        for shift, times in shift_time_ranges.items():
            start_time = datetime.strptime(times["start_time"], "%H:%M:%S").time()
            end_time = datetime.strptime(times["end_time"], "%H:%M:%S").time()

            if start_time <= end_time:  # Regular shift range
                if start_time <= current_time <= end_time:
                    return shift, current_date
            else:  # Overnight shift range
                if current_time >= start_time or current_time <= end_time:
                    # If the shift is overnight and it's after midnight, adjust the date
                    if current_time <= end_time:
                        current_date = current_date.replace(day=current_date.day - 1)
                    return shift, current_date

        return "Unknown Shift", current_date

    current_shift, current_date = get_current_shift_and_date()
    
    print(f"current shift :: {current_shift}, current_date :: {current_date}, type of date :: {type(current_date)}")

    # print(plans_col)
    operator_data = plans_col.find_one({"operator": user,"shift":current_shift,"production_date":str(current_date)})


    print("operator_data ::: ",operator_data)
    # Check if the operator is the same as the user
    if operator_data is  None:
        return "Dont have any Production Plan Please contact Admin" ,{}, 400

    if operator_data.get("operator") != user:
        return "Dont have any Production Plan Please contact Admin" ,{}, 400

        # Check for a valid production plan for the user on the current date
    if user == operator_data.get("operator"):
        # current_time = datetime.now().strftime("%H:%M:%S")
        start_time_str = operator_data.get("start_time")
        end_time_str = operator_data.get("end_time")	

        start_time = datetime.strptime(start_time_str, "%H:%M:%S")
        end_time = datetime.strptime(end_time_str, "%H:%M:%S")

            
        # Get the current time (as a datetime object)
        current_time = datetime.now().strftime("%H:%M:%S")
        current_time = datetime.strptime(current_time, "%H:%M:%S")  # Convert current time to datetime object

        # Print the times for debugging
        print(f"start time :: {start_time} ,type {type(start_time)}, :end time  :::: {type(end_time)}, type :: {end_time}, current time :: {current_time}. type :: {type(current_time)}")

        # Check if current_time is within the range (handling the midnight crossing case)
        if not (start_time <= current_time <= end_time or (start_time > end_time and (current_time >= start_time or current_time <= end_time))):
            # Handle case when current_time is within the range
            return "Don't have any Production Plan. Please contact Admin", {}, 400
        
        else:
            part_name=operator_data.get("part_name")
            part_number=operator_data.get("part_number")
            batch_number=operator_data.get("batch_number")
            shift = operator_data.get("shift")
            insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)
            insreted_obj = insp_col.insert_one({
                "part_name" : part_name,
                "batch_name" : batch_number,
                "part_number":part_number,
                "user" : user,
                "started_at" : datetime.now().strftime(DATE_FORMAT),
                "shift":shift

            })
            inspection_id = str(insreted_obj.inserted_id)
            print("par",part_number,part_name,batch_number,inspection_id)


            curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
            started_at = datetime.now().strftime(DATE_FORMAT)
            curr_insp_col.insert_one({
                "part_name" : part_name,
                "batch_number" : batch_number,
                "part_number":part_number,
                "user" : user,
                "started_at" : started_at ,
                "current_inspection_id" : inspection_id,
                "shift":shift,
                "is_running":True
            })


            plans_col = mongo_helper.read_collection(PLANS_COLLECTION)
            plans_col_data = plans_col.find_one({"part_name":part_name,"part_number":part_number,"operator":user,"shift":shift,"production_date":str(current_date)})
            print("Plans Data :::::::::",plans_col_data)
            if plans_col_data:
                production_date = plans_col_data.get("production_date")

                if production_date in started_at:

                    plans_col_data["status"] = "Running"
                    plans_col.update_one({"_id":plans_col_data.get("_id")},{"$set":plans_col_data})
                
            
            redis_helper.push_data("inspection_id",inspection_id)
            redis_helper.push_data("part_name",part_name)
            redis_helper.push_data("part_number",part_number)

            
            return "Success", {"inspection_id":inspection_id}, 200

def stop_process_util(data):
    current_datetime = datetime.now()
    current_date = current_datetime.date()
    current_inspection_id = data.get("current_inspection_id")
    redis_helper.push_data("inspection_id",None)
    redis_helper.push_data("part_name",None)
    redis_helper.push_data("part_number",None)
    current_date = current_datetime.date()

    if not current_inspection_id:
        return "Please provide current inspection id", {}, 400

    curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
    curr_insp_col_data = curr_insp_col.find_one()
    if curr_insp_col_data:
        part_name = curr_insp_col_data.get("part_name")
        part_number = curr_insp_col_data.get("part_number")
        user = curr_insp_col_data.get("user")
        started_at = curr_insp_col_data.get("started_at")
        shift = curr_insp_col_data.get("shift")





    ### update plan status
    plans_col = mongo_helper.read_collection(PLANS_COLLECTION)
    plans_col_data = plans_col.find_one({"part_name":part_name,"part_number":part_number,"operator":user,"shift":shift,"production_date":str(current_date)})
    if plans_col_data:
        production_date = plans_col_data.get("production_date")

        if production_date in started_at:

            plans_col_data["status"] = "Completed"
            plans_col.update_one({"_id":plans_col_data.get("_id")},{"$set":plans_col_data})




    curr_insp_col.delete_many({})
    insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)
    insp_data = insp_col.find_one({"_id":bson.ObjectId(current_inspection_id)})
    if insp_data:
        insp_data["ended_at"] = datetime.now().strftime(DATE_FORMAT)
        insp_col.update_one({"_id":insp_data["_id"]},{"$set":insp_data})

        
        


        return "Success", {}, 200
    
   
    
    return "Fail", {}, 400



# def stop_process_util(data):
#     current_inspection_id = data.get("current_inspection_id")
#     if not current_inspection_id:
#         return "Please provide current inspection id", {}, 400

#     curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
#     curr_insp_col.delete_one({})
#     insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)
#     insp_data = insp_col.find_one({"_id":bson.ObjectId(current_inspection_id)})
#     if insp_data:
#         insp_data["ended_at"] = datetime.now().strftime(DATE_FORMAT)
#         insp_col.update_one({"_id":insp_data["_id"]},{"$set":insp_data})
#         return "Success", {}, 200
    
#     redis_helper.push_data("inspection_id",None)
#     redis_helper.push_data("part_name",None)
#     redis_helper.push_data("part_number",None)

    
#     return "Fail", {}, 400

def get_inspection_process_status_util():
    curr_insp = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
    curr_insp_data = curr_insp.find_one()
    if curr_insp_data:
        current_inspection_id = curr_insp_data.get("current_inspection_id")
        return "Success", {"current_inspection_id":current_inspection_id}, 200
    else:
        return "Success", {"current_inspection_id":None}, 200



def calculate_defect_ratio(defects_found):
    

    # Calculate total count of all parameters
    total_count = sum(defect['count'] for defect in defects_found)

    # Initialize counters for each category
    critical_count = 0
    major_count = 0
    minor_count = 0

    # Initialize dictionary to store individual defect ratios
    defect_ratios = {}

    # Calculate individual defect ratios and category counts
    for defect in defects_found:
        parameter = defect['parameter']
        count = defect['count']
        category = defect['category']
        
        # Calculate individual defect ratio
        if count == 0:
            individual_ratio = 0
        else:
            individual_ratio = (count / total_count) * 100
        defect_ratios[parameter] = individual_ratio

        # Calculate category counts
        if category == 'critical':
            critical_count += count
        elif category == 'major':
            major_count += count
        elif category == 'minor':
            minor_count += count

    # Calculate category defect ratios
    critical_ratio = (critical_count / total_count) * 100 if total_count > 0 else 0
    major_ratio = (major_count / total_count) * 100 if total_count > 0 else 0
    minor_ratio = (minor_count / total_count) * 100 if total_count > 0 else 0

    # Add category ratios to the defect_ratios dictionary
    # defect_ratios['critical'] = {"category_ratio": critical_ratio}
    # defect_ratios['major'] = {"category_ratio": major_ratio}
    # defect_ratios['minor'] = {"category_ratio": minor_ratio}

    
    defect_ratios['critical'] = critical_ratio
    defect_ratios['major'] = major_ratio
    defect_ratios['minor'] = minor_ratio

    # # Print individual defect ratios
    # print("Individual Defect Ratios:")
    # for parameter, ratios in defect_ratios.items():
    #     if 'individual_ratio' in ratios:
    #         print(f"{parameter} Defect Ratio: {ratios['individual_ratio']:.2f}%")

    # # Print category defect ratios
    # print("\nCategory Defect Ratios:")
    # print(f"Critical Defect Ratio: {defect_ratios['critical']['category_ratio']:.2f}%")
    # print(f"Major Defect Ratio: {defect_ratios['major']['category_ratio']:.2f}%")
    # print(f"Minor Defect Ratio: {defect_ratios['minor']['category_ratio']:.2f}%")


    print(defect_ratios)

    return defect_ratios



####### Windows this below Function Will Work ####################

# def get_disk_usage():
#     partitions = psutil.disk_partitions()
#     total = 0
#     free = 0
#     used = 0
#     for partition in partitions:
#         try : 
#             if "D" in partition.device:
                
#                 try:
#                     usage = psutil.disk_usage(partition.mountpoint)
#                     total += usage.total / (1024**3)
#                     free += usage.free / (1024**3)
#                     used += usage.used / (1024**3)
#                     # print(f"Drive: {partition.device}")
#                     # print(f"  Total Size: {usage.total / (1024**3):.2f} GB")
#                     # print(f"  Used: {usage.used / (1024**3):.2f} GB")
#                     # print(f"  Free: {usage.free / (1024**3):.2f} GB")
#                     # print(f"  Percentage Used: {usage.percent}%\n")

#                 except PermissionError:

#                     continue  # Skip drives that require admin access
#         except Exception as e:
#             print(e)

#     return {"total":total,"free":free,"used":used}


# get_disk_usage()

####### Ubuntu 20.04 this below Function Will Work ####################
import psutil

def get_disk_usage():
    total = 0
    free = 0
    used = 0

    for partition in psutil.disk_partitions():
        if any(x in partition.mountpoint for x in ['snap', 'boot', 'udev', 'run']):
            continue
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            total += usage.total / (1024 ** 3)
            free += usage.free / (1024 ** 3)
            used += usage.used / (1024 ** 3)
        except (PermissionError, FileNotFoundError):
            continue

    return {"total": total, "free": free, "used": used}




# ### old
# def get_quick_inspection_results_util(current_inspection_id):
    
#     insp_col = mongo_helper.read_collection(current_inspection_id+"_logs")
#     OK_data = [i for i in insp_col.find({"status":"OK"})]
#     NOK_data = [i for i in insp_col.find({"status":"NOK"})]


#     # print(NOK_data)

#     if not OK_data:
#         OK_count = 0
#     else:
#         OK_count = len(OK_data)

#     if not NOK_data:
#         NOK_count = 0
#     else:
#         NOK_count = len(NOK_data)


#     total_count = OK_count + NOK_count

#     latest_insp_data = insp_col.find_one(sort=[("_id", DESCENDING)])


#     if latest_insp_data:
#         status = latest_insp_data.get("status")
#         predicted_images = latest_insp_data.get("predicted_images")
#         input_images = latest_insp_data.get("input_images")
#         defects = latest_insp_data.get("defects_found")
#         features = latest_insp_data.get("features")
#         predicted_height = latest_insp_data.get("predicted_height")
#         predicted_width = latest_insp_data.get("predicted_width")
#         predicted_diameter = latest_insp_data.get("predicted_diameter")
#         batch = latest_insp_data.get("batch_name")
#         part_name = latest_insp_data.get("part_name")
#         # cycle_time = latest_insp_data.get("cycle_time")
#         cycle_time = redis_helper.pull_data("cycle_time")
#         defects_ratio = latest_insp_data.get("defect_ratio")
#         predicted_defects = latest_insp_data.get("predicted_defects")
        
    


#     else:
#         status = ""
#         predicted_images = []
#         input_images = []
#         defects = []
#         features = []
#         predicted_width = 0
#         predicted_height  = 0
#         predicted_diameter = 0
#         batch = ""
#         cycle_time = 0
#         part_name= ""
#         defects_ratio = []
    
#     print(defects_ratio,"defects_ratio")

#     overall_critical_count = 0
#     overall_major_count = 0
#     overall_minor_count = 0

#     dd = []
#     for doc in insp_col.find():
#         defects_ratios = doc.get("defect_ratio",None)
#         print(f"defects_ratios :::: {defects_ratios}")
#         overall_critical_count += defects_ratios.get("critical")
#         overall_major_count += defects_ratios.get("major")
#         overall_minor_count += defects_ratios.get("minor")
#         print(overall_critical_count)
#         defects_found = doc.get("defects_found")
#         print(defects_found,"defects found")
#         dd.append(defects_found)

#     #Total defects count calculated 
#     print(dd,"defects all",len(dd))
#     # Initialize a dictionary to store the counts of each category
#     category_count_dict = {}

#     # Loop through each list inside the main list
#     for sublist in dd:
#         for item in sublist:
#             category = item["category"]
#             count= item["count"]
#             # Add to the dictionary or update the count
#             if category in category_count_dict:
#                 category_count_dict[category] += count
#             else:
#                 category_count_dict[category] = count

#     print(category_count_dict,"category_count_dict")
#     # total_defects = sum(category_count_dict.values())
#     overall_critical_count = (category_count_dict.get("critical",0) / len(dd))*100 
#     overall_major_count = (category_count_dict.get("major",0)/ len(dd))*100 
#     overall_minor_count = (category_count_dict.get("minor",0) / len(dd) )*100 

#     print(overall_critical_count,overall_major_count,overall_minor_count)


#     # Initialize a dictionary to sum the counts by parameter
#     parameter_count_dict = {}

#     # Loop through each sublist in the main list
#     for sublist in dd:
#         for item in sublist:
#             parameter = item['parameter']
#             count = item['count']
            
#             # Add to the count for the parameter
#             if parameter in parameter_count_dict:
#                 parameter_count_dict[parameter] += count
#             else:
#                 parameter_count_dict[parameter] = count

#     # Now rebuild the list with updated counts
#     result = []
#     for sublist in dd[0]:  # Use the first sublist to maintain the structure
#         parameter = sublist['parameter']
#         # Update the count from the summed values
#         updated_item = {
#             "parameter": parameter,
#             "accepted": sublist['accepted'],
#             "count": parameter_count_dict[parameter],
#             "category": sublist['category'],
#             "ratio": (parameter_count_dict[parameter] / len(dd))*100
#         }
#         result.append(updated_item)



#     print(result)

#     # curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)
#     # parameter_count_dict = {}

#     # # Assuming mongo_helper is set up for MongoDB interactions

#     # # Read the current inspection collection
#     # curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)

#     # # Initialize a dictionary to store total counts of each parameter and their categories
#     # parameter_count_dict = {}

#     # # Initialize a dictionary to store categories for each defect
#     # parameter_category_dict = {}

#     # # Get the total number of inspections
#     # total_inspections = curr_insp_col.count_documents({})

#     # # Query to get all documents from current inspection collection
#     # inspection_docs = curr_insp_col.find()

#     # # Loop through all inspection docs from current inspection collection
#     # for doc in inspection_docs:
#     #     defects_found = doc.get("consolidated_defects_found", [])
        
#     #     # Loop through each defect in defects_found
#     #     for item in defects_found:
#     #         parameter = item['parameter']
#     #         count = item['count']
#     #         category = item['category']
#     #         accepted = item['accepted']
            
#     #         # Sum the counts of each parameter across all inspections
#     #         if parameter in parameter_count_dict:
#     #             parameter_count_dict[parameter] += count
#     #         else:
#     #             parameter_count_dict[parameter] = count
            
#     #         # Keep track of the category for each defect
#     #         if parameter not in parameter_category_dict:
#     #             parameter_category_dict[parameter] = category

#     # # Now create the output with the specific format
#     # result = []

#     # for parameter in parameter_count_dict:
#     #     # Calculate the ratio as (total_count / total_inspections) * 100
#     #     total_count = parameter_count_dict[parameter]
#     #     ratio = (total_count / total_inspections) * 100
#     #     category = parameter_category_dict.get(parameter, "unknown")  # Default to "unknown" if no category is found
#     #     accepted = True  # Assuming all defects are accepted as true based on your example

#     #     # Construct the result item for each defect
#     #     result.append({
#     #         "parameter": parameter,
#     #         "accepted": accepted,
#     #         "count": total_count,
#     #         "category": category,
#     #         "ratio": ratio
#     #     })

#     # # Print the result
#     # print(result)

#     # cycle_time = latest_insp_data.get("cycle_time",0)
#     # cycle_time = (cycle_time * 1000)

#     return "Success", {
#         "input_images": input_images,
#         "predicted_images" : predicted_images,
#         "defects_found" : result,
#         "features" : features,
#         "predicted_height" : predicted_height,
#         "predicted_width" : predicted_width,
#         "predicted_diameter" : predicted_diameter,
#         "status" : status,
#         "OK_count" : OK_count,
#         "NOK_count" : NOK_count,
#         "total_count" : total_count,
#         "cycle_time" : cycle_time,
#         "batch_name": batch,
#         "part_name" : part_name,
#         "defect_ratio" : defects_ratio,
#         "overall_minor_count" : overall_minor_count,
#         "overall_major_count" : overall_major_count,
#         "overall_critical_count" : overall_critical_count,
#         "predicted_defects":predicted_defects
#     }, 200


## new
# def get_quick_inspection_results_util(current_inspection_id):



#     status = ""
#     predicted_images = []
#     input_images = []
#     defects = []
#     features = []
#     predicted_width = 0
#     predicted_height  = 0
#     predicted_diameter = 0
#     batch = ""
#     cycle_time = 0
#     part_name= ""
#     defects_ratio = []
#     predicted_defects = []
    
#     # insp_col = mongo_helper.read_collection(current_inspection_id+"_logs")

#     # latest_insp_data = insp_col.find_one(sort=[("_id", DESCENDING)])
#     # curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)



#     # if latest_insp_data:
#     #     status = latest_insp_data.get("status")
#     #     predicted_images = latest_insp_data.get("predicted_images")
#     #     input_images = latest_insp_data.get("input_images")
#     #     defects = latest_insp_data.get("defects_found")
#     #     features = latest_insp_data.get("features")
#     #     predicted_height = latest_insp_data.get("predicted_height")
#     #     predicted_width = latest_insp_data.get("predicted_width")
#     #     predicted_diameter = latest_insp_data.get("predicted_diameter")
#     #     batch = latest_insp_data.get("batch_name")
#     #     part_name = latest_insp_data.get("part_name")
#     #     cycle_time = latest_insp_data.get("cycle_time")
#     #     # cycle_time = redis_helper.pull_data("cycle_time")
#     #     defects_ratio = latest_insp_data.get("defect_ratio")
#     #     predicted_defects = latest_insp_data.get("predicted_defects")
        
    


#     # else:
#     #     status = ""
#     #     predicted_images = []
#     #     input_images = []
#     #     defects = []
#     #     features = []
#     #     predicted_width = 0
#     #     predicted_height  = 0
#     #     predicted_diameter = 0
#     #     batch = ""
#     #     cycle_time = 0
#     #     part_name= ""
#     #     defects_ratio = []
#     #     predicted_defects = []



#     # parameter_count_dict = {}

#     # # Assuming mongo_helper is set up for MongoDB interactions

#     # Read the current inspection collection
#     curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)

#     # # Initialize a dictionary to store total counts of each parameter and their categories
#     # parameter_count_dict = {}

#     # # Initialize a dictionary to store categories for each defect
#     # parameter_category_dict = {}

#     # # Get the total number of inspections
#     # total_inspections = curr_insp_col.count_documents({})

#     # # Query to get all documents from current inspection collection
#     # inspection_docs = curr_insp_col.find()

#     # # Loop through all inspection docs from current inspection collection
#     # for doc in inspection_docs:
#     #     defects_found = doc.get("consolidated_defects_found", [])
        
#     #     # Loop through each defect in defects_found
#     #     for item in defects_found:
#     #         parameter = item['parameter']
#     #         count = item['count']
#     #         category = item['category']
#     #         accepted = item['accepted']
            
#     #         # Sum the counts of each parameter across all inspections
#     #         if parameter in parameter_count_dict:
#     #             parameter_count_dict[parameter] += count
#     #         else:
#     #             parameter_count_dict[parameter] = count
            
#     #         # Keep track of the category for each defect
#     #         if parameter not in parameter_category_dict:
#     #             parameter_category_dict[parameter] = category

#     # # Now create the output with the specific format
#     # result = []

#     # for parameter in parameter_count_dict:
#     #     # Calculate the ratio as (total_count / total_inspections) * 100
#     #     total_count = parameter_count_dict[parameter]
#     #     ratio = (total_count / total_inspections) * 100
#     #     category = parameter_category_dict.get(parameter, "unknown")  # Default to "unknown" if no category is found
#     #     accepted = True  # Assuming all defects are accepted as true based on your example

#     #     # Construct the result item for each defect
#     #     result.append({
#     #         "parameter": parameter,
#     #         "accepted": accepted,
#     #         "count": total_count,
#     #         "category": category,
#     #         "ratio": ratio
#     #     })

#     # # Print the result
#     # print(result)
#     # latest_one_data = curr_insp_col.find_one()
#     # OK_count = latest_one_data.get("OK",0)
#     # NOK_count = latest_one_data.get("NOK",0)

#     # overall_minor_count = 0
#     # overall_major_count = 0
#     # overall_critical_count = 0


#     ############# ratio finding ##############
        
    
   
#     curr_insp_col_data = curr_insp_col.find_one()
#     OK_count = curr_insp_col_data.get("OK",0)
#     NOK_count = curr_insp_col_data.get("NOK",0)
#     status = curr_insp_col_data.get("status")
#     cycle_time = curr_insp_col_data.get("cycle_time")
#     part_name = curr_insp_col_data.get("part_name")
#     batch_number = curr_insp_col_data.get("batch_number")




#     consolidated_defects_found = curr_insp_col_data.get("consolidated_defects_found",[])
#     # Initialize defect ratio with parameter-wise counts and categories
#     defect_ratio = defaultdict(lambda: {"count": 0, "category": set()})
#     total_defect_count = 0  # Initialize total defect count

#     # Initialize category-specific defect counts
#     major_count = 0
#     minor_count = 0
#     critical_count = 0

    
#     if consolidated_defects_found:
#         # Iterate through defect records
#         for doc in consolidated_defects_found:
#             parameter = doc.get("parameter")
#             count = doc.get("count", 0)  # Default to 0 if count is missing
#             category = doc.get("category", "Unknown")  # Default to "Unknown" if category is missing
      
#             # Categorize defect counts
#             if category == "minor":
#                 minor_count += count
#             elif category == "major":
#                 major_count += count
#             elif category == "critical":
#                 critical_count += count

#             # Store count and category in defect_ratio
#             defect_ratio[parameter]["count"] += count
#             defect_ratio[parameter]["category"].add(category)  # Use set to avoid duplicates

#             total_defect_count += count  # Accumulate total defect count

#         # Convert categories set to list for better readability
#         for param, data in defect_ratio.items():
#             data["category"] = list(data["category"])

#         # Calculate defect percentage per parameter
#         defect_percentage = {
#             param: {
#                 "count": data["count"],
#                 "category": data["category"],
#                 "percentage": (data["count"] / total_defect_count * 100) if total_defect_count > 0 else 0
#             }
#             for param, data in defect_ratio.items()
#         }


#         # Print results
#         print("Defect Ratio:", defect_percentage)
#         print("Total Defect Count:", total_defect_count)



#         critical_ratio = (critical_count / total_defect_count) * 100
#         major_ratio = (major_count / total_defect_count) * 100
#         minor_ratio = (minor_count / total_defect_count) * 100

#         print(critical_ratio)
#         print(major_ratio)
#         print(minor_ratio)

#         print("total ratio ::",critical_ratio+major_ratio+minor_ratio)


#     else:

#         defect_percentage = {}
#         minor_ratio = 0
#         major_ratio = 0
#         critical_ratio = 0




#     # result = defects
#     return "Success", {
#         "input_images": input_images,
#         "predicted_images" : predicted_images,
#         "defects_found" : defects,
#         "features" : features,
#         "predicted_height" : predicted_height,
#         "predicted_width" : predicted_width,
#         "predicted_diameter" : predicted_diameter,
#         "status" : status,
#         "OK_count" : OK_count,
#         "NOK_count" : NOK_count,
#         "total_count" : OK_count + NOK_count,
#         "cycle_time" : cycle_time,
#         "batch_name": batch_number,
#         "part_name" : part_name,
#         "defect_ratio" : defects_ratio,
#         "overall_minor_count" : minor_ratio,
#         "overall_major_count" : major_ratio,
#         "overall_critical_count" : critical_ratio,
#         "predicted_defects":predicted_defects,
#         "defect_summery_ratio" : defect_percentage,
#     }, 200



def get_quick_inspection_results_util(current_inspection_id):



    status = ""
    predicted_images = []
    input_images = []
    defects = []
    features = []
    predicted_width = 0
    predicted_height  = 0
    predicted_diameter = 0
    batch = ""
    cycle_time = 0
    part_name= ""
    defects_ratio = []
    predicted_defects = []
    
    # insp_col = mongo_helper.read_collection(current_inspection_id+"_logs")

    # latest_insp_data = insp_col.find_one(sort=[("_id", DESCENDING)])
    # curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)



    # if latest_insp_data:
    #     status = latest_insp_data.get("status")
    #     predicted_images = latest_insp_data.get("predicted_images")
    #     input_images = latest_insp_data.get("input_images")
    #     defects = latest_insp_data.get("defects_found")
    #     features = latest_insp_data.get("features")
    #     predicted_height = latest_insp_data.get("predicted_height")
    #     predicted_width = latest_insp_data.get("predicted_width")
    #     predicted_diameter = latest_insp_data.get("predicted_diameter")
    #     batch = latest_insp_data.get("batch_name")
    #     part_name = latest_insp_data.get("part_name")
    #     cycle_time = latest_insp_data.get("cycle_time")
    #     # cycle_time = redis_helper.pull_data("cycle_time")
    #     defects_ratio = latest_insp_data.get("defect_ratio")
    #     predicted_defects = latest_insp_data.get("predicted_defects")
        
    


    # else:
    #     status = ""
    #     predicted_images = []
    #     input_images = []
    #     defects = []
    #     features = []
    #     predicted_width = 0
    #     predicted_height  = 0
    #     predicted_diameter = 0
    #     batch = ""
    #     cycle_time = 0
    #     part_name= ""
    #     defects_ratio = []
    #     predicted_defects = []



    # parameter_count_dict = {}

    # # Assuming mongo_helper is set up for MongoDB interactions

    # Read the current inspection collection
    curr_insp_col = mongo_helper.read_collection(CURRENT_INSPECTION_COLLECTION)

    # # Initialize a dictionary to store total counts of each parameter and their categories
    # parameter_count_dict = {}

    # # Initialize a dictionary to store categories for each defect
    # parameter_category_dict = {}

    # # Get the total number of inspections
    # total_inspections = curr_insp_col.count_documents({})

    # # Query to get all documents from current inspection collection
    # inspection_docs = curr_insp_col.find()

    # # Loop through all inspection docs from current inspection collection
    # for doc in inspection_docs:
    #     defects_found = doc.get("consolidated_defects_found", [])
        
    #     # Loop through each defect in defects_found
    #     for item in defects_found:
    #         parameter = item['parameter']
    #         count = item['count']
    #         category = item['category']
    #         accepted = item['accepted']
            
    #         # Sum the counts of each parameter across all inspections
    #         if parameter in parameter_count_dict:
    #             parameter_count_dict[parameter] += count
    #         else:
    #             parameter_count_dict[parameter] = count
            
    #         # Keep track of the category for each defect
    #         if parameter not in parameter_category_dict:
    #             parameter_category_dict[parameter] = category

    # # Now create the output with the specific format
    # result = []

    # for parameter in parameter_count_dict:
    #     # Calculate the ratio as (total_count / total_inspections) * 100
    #     total_count = parameter_count_dict[parameter]
    #     ratio = (total_count / total_inspections) * 100
    #     category = parameter_category_dict.get(parameter, "unknown")  # Default to "unknown" if no category is found
    #     accepted = True  # Assuming all defects are accepted as true based on your example

    #     # Construct the result item for each defect
    #     result.append({
    #         "parameter": parameter,
    #         "accepted": accepted,
    #         "count": total_count,
    #         "category": category,
    #         "ratio": ratio
    #     })

    # # Print the result
    # print(result)
    # latest_one_data = curr_insp_col.find_one()
    # OK_count = latest_one_data.get("OK",0)
    # NOK_count = latest_one_data.get("NOK",0)

    # overall_minor_count = 0
    # overall_major_count = 0
    # overall_critical_count = 0


    ############# ratio finding ##############
        
    
   
    curr_insp_col_data = curr_insp_col.find_one()
    OK_count = curr_insp_col_data.get("OK",0)
    NOK_count = curr_insp_col_data.get("NOK",0)
    REWORK_count = curr_insp_col_data.get("REWORK",0)
    status = curr_insp_col_data.get("status")
    cycle_time = curr_insp_col_data.get("cycle_time")
    part_name = curr_insp_col_data.get("part_name")
    batch_number = curr_insp_col_data.get("batch_number")
    predicted_defects = curr_insp_col_data.get("predicted_defects")




    consolidated_defects_found = curr_insp_col_data.get("consolidated_defects_found",[])
    # Initialize defect ratio with parameter-wise counts and categories
    defect_ratio = defaultdict(lambda: {"count": 0, "category": set()})
    total_defect_count = 0  # Initialize total defect count

    # Initialize category-specific defect counts
    major_count = 0
    minor_count = 0
    critical_count = 0
    rework_count = 0

    
    if consolidated_defects_found:
        # Iterate through defect records
        for doc in consolidated_defects_found:
            parameter = doc.get("parameter")
            count = doc.get("count", 0)  # Default to 0 if count is missing
            category = doc.get("category", "Unknown")  # Default to "Unknown" if category is missing
      
            # Categorize defect counts
            if category == "minor":
                minor_count += count
            elif category == "major":
                major_count += count
            elif category == "critical":
                critical_count += count
            elif category == "rework":
                rework_count += count

            # Store count and category in defect_ratio
            defect_ratio[parameter]["count"] += count
            defect_ratio[parameter]["category"].add(category)  # Use set to avoid duplicates

            total_defect_count += count  # Accumulate total defect count

        # Convert categories set to list for better readability
        for param, data in defect_ratio.items():
            data["category"] = list(data["category"])

        # Calculate defect percentage per parameter
        defect_percentage = {
            param: {
                "count": data["count"],
                "category": data["category"],
                "percentage": (data["count"] / total_defect_count * 100) if total_defect_count > 0 else 0
            }
            for param, data in defect_ratio.items()
        }


        # Print results
        # print("Defect Ratio:", defect_percentage)
        # print("Total Defect Count:", total_defect_count)



        critical_ratio = (critical_count / total_defect_count) * 100
        major_ratio = (major_count / total_defect_count) * 100
        minor_ratio = (minor_count / total_defect_count) * 100
        rework_ratio = (rework_count / total_defect_count) * 100



        # print(critical_ratio)
        # print(major_ratio)
        # print(minor_ratio)

        # print("total ratio ::",critical_ratio+major_ratio+minor_ratio)


    else:

        defect_percentage = {}
        minor_ratio = 0
        major_ratio = 0
        critical_ratio = 0
        rework_ratio = 0




    # result = defects
    return "Success", {
        "input_images": input_images,
        "predicted_images" : predicted_images,
        "defects_found" : defects,
        "features" : features,
        "predicted_height" : predicted_height,
        "predicted_width" : predicted_width,
        "predicted_diameter" : predicted_diameter,
        "status" : status,
        "OK_count" : OK_count,
        "NOK_count" : NOK_count,
        "REWORK_count" : REWORK_count,
        "total_count" : OK_count + NOK_count + REWORK_count,
        "cycle_time" : cycle_time,
        "batch_name": batch_number,
        "part_name" : part_name,
        "defect_ratio" : defects_ratio,
        "overall_minor_count" : minor_ratio,
        "overall_major_count" : major_ratio,
        "overall_critical_count" : critical_ratio,
        "overall_rework_count" : rework_ratio,
        "predicted_defects":predicted_defects,
        "defect_summery_ratio" : defect_percentage,
    }, 200



def health_check_util():
    camera_health = redis_helper.pull_data("camera_health")
    plc_health = redis_helper.pull_data("plc_health")
    camera_message = redis_helper.pull_data("camera_message")
    plc_message = redis_helper.pull_data("plc_message")

    # camera_health = True
    # plc_health = True
    # camera_message = ""
    # plc_message = ""
    disk_health = get_disk_usage()
    total = disk_health.get("total")
    free = disk_health.get("free")
    used = disk_health.get("used")
    if free <= 50: ## GB
        storage_health = False 
        storage_message = f"Disk is getting filled , Please take backup your data. "
    else:
        storage_health = True
        storage_message = ""

    resp = {
        CAMERA_HEALTH : camera_health,
        PLC_HEALTH : plc_health,
        PLC_MESSAGE : plc_message,
        CAMERA_MESSAGE : camera_message,
        STORAGE_HEALTH : storage_health,
        STORAGE_MESSAGE : storage_message,
        "disk_total" : round(total,2),
        "disk_free" : round(free,2),
        "disk_used" : round(used,2)




    }
    return "Success",resp,200



########### Reports Utils #################################

# def get_reports_util(data):
# 	start_time = data.get("start_time")
# 	end_time = data.get("end_time")
# 	status = data.get("status")
# 	part_name = data.get("part_name")
# 	batch_number = data.get("batch_number")
# 	part_number = data.get("part_number")
# 	model_number = data.get("model_number")
# 	user = data.get("user")


    
# 	query  = []
# 	if part_name:
# 		query.append({"part_name":part_name})
# 	if batch_number:
# 		query.append({"batch_name":batch_number})
# 	if part_number:
# 		query.append({"part_number":part_number})
# 	if model_number:
# 		query.append({"model_number":model_number})
# 	if user:
# 		query.append({"user":user})


    
# 	if start_time and end_time:
# 		# Ensure both times are in datetime format (or MongoDB compatible format)
# 		try:
    
# 			query.append({"started_at": {"$gte": start_time, "$lte": end_time}})
# 		except ValueError:
# 			# If the time format is incorrect, handle the exception (could be logging here)
# 			return "Invalid start_time or end_time format", {}, 400
    

# 	insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)
# 	if query:
# 		insp_col_data = [i for i in insp_col.find({"$and": query}).sort("_id",-1)]
# 	else:
# 		# If no filters are provided, return all data
# 		insp_col_data = [i for i in insp_col.find().sort("_id",-1)]
    
# 	# print(insp_col_data,"inspe col data")
# 	total_data = []
    
# 	for obj in insp_col_data:
# 		id = obj.get("_id")	
# 		# print(f"iddddddd :: {id}")

# 		log_col = mongo_helper.read_collection(str(id)+"_logs")
# 		if status:
# 			log_col_data =  [i for i in log_col.find({"status":status}).sort("_id",-1)]

# 		else:
# 			log_col_data =  [i for i in log_col.find().sort("_id",-1)]

        

      
# 		total_data.extend(log_col_data)
# 		# print("................................total data ...........................",total_data)

# 	ok_data = 0
# 	nok_data = 0

# 	for obj in total_data:
# 		if obj.get("status") == "OK":
# 			ok_data +=1
# 		elif obj.get("status") == "NOK":
# 			nok_data +=1

# 	response = {"data":total_data,"ok_count":ok_data,"nok_count":nok_data,"total":len(total_data)}

# 	return "Success",response, 200

# def get_reports_util(data):
#     start_time = data.get("start_time")
#     end_time = data.get("end_time")
#     status = data.get("status")
#     part_name = data.get("part_name")
#     batch_number = data.get("batch_number")
#     part_number = data.get("part_number")
#     model_number = data.get("model_number")
#     user = data.get("user")
    
#     query = []
    
#     if part_name:
#         query.append({"part_name": part_name})
#     if batch_number:
#         query.append({"batch_name": batch_number})
#     if part_number:
#         query.append({"part_number": part_number})
#     if model_number:
#         query.append({"model_number": model_number})
#     if user:
#         query.append({"user": user})

#     if start_time and end_time:
#         try:
#             query.append({"started_at": {"$gte": start_time, "$lte": end_time}})
#         except ValueError:
#             return "Invalid start_time or end_time format", {}, 400

#     # Start by querying the inspections collection
#     insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)

#     # If query is empty, match all documents, otherwise use the $and filter
#     match_stage = {"$match": {}} if not query else {"$match": {"$and": query}}

#     # Aggregation pipeline
#     pipeline = [match_stage, {"$sort": {"_id": DESCENDING}}, {"$limit": 5}]
    
#     try:
#         # Perform aggregation to get the latest inspections
#         inspections = list(insp_col.aggregate(pipeline))
#         print(f"Inspections fetched: {len(inspections)}")  # Debugging step
#     except Exception as e:
#         return str(e), {}, 500

#     total_data = []
#     for inspection in inspections:
#         inspection_id = inspection.get("_id")
#         log_col = mongo_helper.read_collection(f"{inspection_id}_logs")
#         print(f"Fetching logs from collection: {inspection_id}_logs")  # Debugging step

#         log_pipeline = [{"$match": {}}, {"$sort": {"_id": DESCENDING}}, {"$limit": 100}]
        
#         try:
#             log_data = list(log_col.aggregate(log_pipeline))
#             print(f"Logs fetched for inspection {inspection_id}: {len(log_data)}")  # Debugging step
#         except Exception as e:
#             return str(e), {}, 500

#         total_data.extend(log_data)

#     # Calculate counts of OK and NOK statuses
#     ok_data = sum(1 for obj in total_data if obj.get("status") == "OK")
#     nok_data = sum(1 for obj in total_data if obj.get("status") == "NOK")

#     # Return the response
#     response = {
#         "data": total_data,
#         "ok_count": ok_data,
#         "nok_count": nok_data,
#         "total": len(total_data)
#     }

#     return "Success", response, 200





# def get_reports_util(data):
#     start_time = data.get("start_time")
#     end_time = data.get("end_time")
#     status = data.get("status")
#     part_name = data.get("part_name")
#     batch_number = data.get("batch_number")
#     part_number = data.get("part_number")
#     model_number = data.get("model_number")
#     user = data.get("user")

#     query = []

#     # Get current date and the relevant datetime objects for filtering
#     now = datetime.now()
#     yesterday = now - timedelta(days=1)
#     yesterday_date = yesterday.date()
#     if data is None:
#         return "Error: No data received", {}, 400  # Handle this case properly


#     # Assuming data is a dictionary with the keys: today, yesterday, last_2_shifts, last_3_shifts, last_1_shifts
#     # today_check = data.get("report_type").get("today")
#     report_type = data.get("report_type", {})
#     today_check = report_type.get("today", False)
#     # yesterday_check = report_type.get("yesterday", False)
#     # # last_2_shift3_check = 
#     # # last_3_shifts_check = 

#     yesterday_check = data.get("report_type").get("yesterday")
#     yesterday_check = report_type.get("yesterday", False)
#     last_2_shift3_check = data.get("report_type").get("last_2_shifts" )
#     last_3_shifts_check = data.get("report_type").get("last_3_shifts" )
#     last_1_shifts_check = data.get("report_type").get("last_1_shifts" )
#     current_shift_check = data.get("report_type").get("current_shift" )
#     last_30_days_check = data.get("report_type").get("last_30_days" )
#     last_15_days_check = data.get("report_type").get("last_15_days" )
#     last_7_days_check = data.get("report_type").get("last_7_days")


    
    
    
        
#     # Get today's date in the required format
#     today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
#     today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=999999)

#     # # Shift ranges
#     # shift_time_ranges = {
#     # 	"shift a": {"start_time": "06:00:00", "end_time": "13:59:59"},
#     # 	"shift b": {"start_time": "14:00:00", "end_time": "21:59:59"},
#     # 	"shift c": {"start_time": "22:00:00", "end_time": "05:59:59"}
#     # }

#     shift_time_ranges = SHIFTS
#     def get_shift_for_time(current_time):
#         # Determine which shift it is based on the time of day
#         for shift, times in shift_time_ranges.items():
#             shift_start = datetime.strptime(times["start_time"], "%H:%M:%S").time()
#             shift_end = datetime.strptime(times["end_time"], "%H:%M:%S").time()

#             if shift_start <= current_time.time() <= shift_end:
#                 return shift
#         return "Shift C"  # Default to shift c if no match

#     # If 'today' is set, filter for today's data
#     if today_check:
#         query.append({
#             "started_at": {
#                 "$gte": today_start.strftime(DATE_FORMAT),
#                 "$lte": today_end.strftime(DATE_FORMAT)
#             }
#         })

#     # Get yesterday's date
#     yesterday_start = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
#     yesterday_end = (datetime.now() - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)

#     # If 'yesterday' is set, filter for yesterday's data
#     if yesterday_check:
#         query.append({
#             "started_at": {
#                 "$gte": yesterday_start.strftime(DATE_FORMAT),
#                 "$lte": yesterday_end.strftime(DATE_FORMAT)
#             }
#         })

#     # If 'last_2_shifts' is set, filter for the last 2 shifts
#     elif last_2_shift3_check:
#         last_2_end = datetime.combine(now.date(), datetime.max.time())
#         last_2_start = last_2_end - timedelta(hours=16)  # Assuming each shift is 8 hours
#         query.append({
#             "started_at": {
#                 "$gte": last_2_start.strftime(DATE_FORMAT),
#                 "$lte": last_2_end.strftime(DATE_FORMAT)
#             }
#         })

#     # If 'last_3_shifts' is set, filter for the last 3 shifts
#     elif last_3_shifts_check:
#         last_3_end = datetime.combine(now.date(), datetime.max.time())
#         last_3_start = last_3_end - timedelta(hours=24)  # Assuming each shift is 8 hours
#         query.append({
#             "started_at": {
#                 "$gte": last_3_start.strftime(DATE_FORMAT),
#                 "$lte": last_3_end.strftime(DATE_FORMAT)
#             }
#         })

#     elif last_1_shifts_check:
#         last_shift_time = datetime.combine(yesterday_date, datetime.max.time())
#         last_shift = get_shift_for_time(last_shift_time)
#         shift_times = shift_time_ranges[last_shift]
        
#         shift_start_time = datetime.combine(yesterday_date, datetime.strptime(shift_times["start_time"], "%H:%M:%S").time())
#         shift_end_time = datetime.combine(yesterday_date, datetime.strptime(shift_times["end_time"], "%H:%M:%S").time())

#         if last_shift == "Shift C" and last_shift_time.time() < datetime.strptime("06:00:00", "%H:%M:%S").time():
#             shift_start_time = shift_start_time - timedelta(days=1)  # Shift C goes past midnight, adjust for the previous day

#         query.append({
#             "started_at": {
#                 "$gte": shift_start_time.strftime(DATE_FORMAT),
#                 "$lte": shift_end_time.strftime(DATE_FORMAT)
#             }
#         })
#     # If 'current_shift' is set, filter for the current shift
#     elif current_shift_check:
#         current_shift = get_shift_for_time(now)
#         print(current_shift,"currnet shift")

#         shift_times = shift_time_ranges[current_shift]
        
#         shift_start_time = datetime.combine(now.date(), datetime.strptime(shift_times["start_time"], "%H:%M:%S").time())
#         shift_end_time = datetime.combine(now.date(), datetime.strptime(shift_times["end_time"], "%H:%M:%S").time())

#         if current_shift == "shift c" and now.time() < datetime.strptime("06:00:00", "%H:%M:%S").time():
#             shift_start_time = shift_start_time - timedelta(days=1)  # Shift C goes past midnight, adjust for the previous day

#         query.append({
#             "started_at": {
#                 "$gte": shift_start_time.strftime(DATE_FORMAT),
#                 "$lte": shift_end_time.strftime(DATE_FORMAT)
#             }
#         })
    

#     # If 'last_30_days' is set, filter for the last 30 days' data
#     elif last_30_days_check:
#         last_30_start = now - timedelta(days=30)
#         query.append({
#             "started_at": {
#                 "$gte": last_30_start.strftime(DATE_FORMAT),
#                 "$lte": now.strftime(DATE_FORMAT)
#             }
#         })

#     # If 'last_15_days' is set, filter for the last 15 days' data
#     elif last_15_days_check:
#         last_15_start = now - timedelta(days=15)
#         query.append({
#             "started_at": {
#                 "$gte": last_15_start.strftime(DATE_FORMAT),
#                 "$lte": now.strftime(DATE_FORMAT)
#             }
#         })

#     # If 'last_7_days' is set, filter for the last 7 days' data
#     elif last_7_days_check:
#         last_7_start = now - timedelta(days=7)
#         query.append({
#             "started_at": {
#                 "$gte": last_7_start.strftime(DATE_FORMAT),
#                 "$lte": now.strftime(DATE_FORMAT)
#             }
#         })


#     print(query)
#     if not query:

#         if part_name:
#             query.append({"part_name": part_name})
#         if batch_number:
#             query.append({"batch_name": batch_number})
#         if part_number:
#             query.append({"part_number": part_number})
#         if model_number:
#             query.append({"model_number": model_number})
#         if user:
#             query.append({"user": user})
        



#     if start_time and end_time:
#         try:
#             query.append({"started_at": {"$gte": start_time, "$lte": end_time}})
#         except ValueError:
#             return "Invalid start_time or end_time format", {}, 400

#     insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)

#     if query:
#         insp_col_data = [i for i in insp_col.find({"$and": query}).sort("_id", -1)]
#     else:
#         insp_col_data = [i for i in insp_col.find().sort("_id", -1)]

#     total_data = []
#     for obj in insp_col_data:
#         id = obj.get("_id")
#         log_col = mongo_helper.read_collection(str(id) + "_logs")
#         if status:
#             log_col_data = [i for i in log_col.find({"status": status}).sort("_id", -1)]
#         else:
#             log_col_data = [i for i in log_col.find().sort("_id", -1)]
#         total_data.extend(log_col_data)

#     # Calculate overall counts
#     ok_data = sum(1 for obj in total_data if obj.get("status") == "OK")
#     nok_data = sum(1 for obj in total_data if obj.get("status") == "NOK")
#     total_records = len(total_data)

#     # Limit the response to 500 latest records
#     total_data = sorted(total_data, key=lambda x: x.get("_id"), reverse=True)

#     response = {
#         "data": total_data,
#         "ok_count": ok_data,
#         "nok_count": nok_data,
#         "total": total_records,
#         }

#     return "Success", response, 200



def find_inspection_yield(total_passed,total_isnpections):
    try :
        inspection_yield = ( total_passed / total_isnpections ) * 100
    except Exception as e:
        inspection_yield = 0

    return inspection_yield

def find_defect_ppm(total_nok,total):
    try:
        defect_ppm = (total_nok / total )*1000000
        
    except Exception as e:
        defect_ppm = 0
        
    return defect_ppm


def get_shift_for_time(now):
    # Get current time
    shift_times = SHIFTS
    now = now.time()

    for shift, times in shift_times.items():
        start = datetime.strptime(times['start_time'], "%H:%M:%S").time()
        end = datetime.strptime(times['end_time'], "%H:%M:%S").time()

        # Handle overnight shift
        if start <= end:
            if start <= now <= end:
                return shift
        else:  # Overnight case (Shift C)
            if now >= start or now <= end:
                return shift
    
    return None  # If no shift matche


def get_previous_shift():
    
    now = datetime.now().time()  # Get current time
    
    shift_order = ["Shift A", "Shift B", "Shift C"]
    
    # Convert shift times to datetime.time objects
    shift_times = {
        shift: {"start": datetime.strptime(times["start_time"], "%H:%M:%S").time(),
                "end": datetime.strptime(times["end_time"], "%H:%M:%S").time()}
        for shift, times in SHIFTS.items()
    }

    # Determine the current shift
    for i, shift in enumerate(shift_order):
        start = shift_times[shift]["start"]
        end = shift_times[shift]["end"]

        if start < end:  # Normal shift timing
            if start <= now <= end:
                return shift_order[i - 1] if i > 0 else "Shift C"  # Previous shift
        else:  # Night shift (crosses midnight)
            if now >= start or now <= end:
                return shift_order[i - 1] if i > 0 else "Shift C"  # Previous shift
    
    # return None  # Fallback case
    return "No data available",{},200



###################### Reports Utils ########################################

class FastTrackReports:
    

    def get_last_2_shifts_data(self):
        pass





def get_reports_util_run(data):
    # if not data or not isinstance(data, dict):
    #     return "Error: No valid data received", {}, 400  # Ensure data is a dictionary
    # if not data:
    #     return {"message": "No filters applied, returning default data", "data": [], "status_code": 200}

    print(f"payload :: {data}")
    
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    status = data.get("status", None)
    part_name = data.get("part_name", None)
    batch_number = data.get("batch_number", None)
    part_number = data.get("part_number", None)
    model_number = data.get("model_number", None)
    user = data.get("user", None)

    query = []
    now = datetime.now()
    
    # Default to empty dictionary if report_type is missing
    report_type = data.get("report_type", {})

    # print(report_type,"report type ")
    # Ensure report type values are boolean or handle missing keys
    today_check = bool(report_type.get("today", False))
    yesterday_check = bool(report_type.get("yesterday", False))
    last_2_shift3_check = bool(report_type.get("last_2_shifts", False))
    last_3_shifts_check = bool(report_type.get("last_3_shifts", False))
    last_1_shifts_check = bool(report_type.get("last_1_shifts", False))
    current_shift_check = bool(report_type.get("current_shift", False))
    last_30_days_check = bool(report_type.get("last_30_days", False))
    last_15_days_check = bool(report_type.get("last_15_days", False))
    last_7_days_check = bool(report_type.get("last_7_days", False))

    # Get today's start and end time
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Add date-based filters safely
    if today_check:
        query.append({
            "started_at": {"$gte": today_start.strftime(DATE_FORMAT), "$lte": today_end.strftime(DATE_FORMAT)}
        })

    # Yesterday's date range
    yesterday = now - timedelta(days=1)
    yesterday_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

    if yesterday_check:
        query.append({
            "started_at": {"$gte": yesterday_start.strftime(DATE_FORMAT), "$lte": yesterday_end.strftime(DATE_FORMAT)}
        })

    # Handle shift-based filtering only if shifts are defined
    if 'SHIFTS' in globals():
        shift_time_ranges = SHIFTS  # Ensure SHIFTS is available
    else:
        return "Error: Shift configuration missing", {}, 500

   
    

    # Last shifts handling
    if last_2_shift3_check:
        last_2_start = now - timedelta(hours=16)
        query.append({
            "started_at": {"$gte": last_2_start.strftime(DATE_FORMAT), "$lte": now.strftime(DATE_FORMAT)}
        })

    if last_3_shifts_check:
        last_3_start = now - timedelta(hours=24)
        query.append({
            "started_at": {"$gte": last_3_start.strftime(DATE_FORMAT), "$lte": now.strftime(DATE_FORMAT)}
        })

    if last_1_shifts_check:
        print("in elif ")
        last_shift_time = yesterday.replace(hour=23, minute=59, second=59)
        print(last_shift_time,"last shift time")

        last_shift = get_shift_for_time(last_shift_time)
        print(last_shift,"last shift")
        last_shift = get_previous_shift()
        print(last_shift,"last shift")


        if last_shift and last_shift in shift_time_ranges:
            shift_times = shift_time_ranges[last_shift]
            print(shift_times,"shift times")
            
            # shift_start_time = yesterday.replace(hour=int(shift_times["start_time"].split(":")[0]))
            # shift_end_time = yesterday.replace(hour=int(shift_times["end_time"].split(":")[0]))
            # print(f"shift start time :: {shift_start_time}, shift end time :: {shift_end_time}")
            # # query.append({
            # #     "started_at": {"$gte": shift_start_time.strftime(DATE_FORMAT), "$lte": shift_end_time.strftime(DATE_FORMAT)}
            # # })
            # query.append({
            #     "started_at": {"$gte": today_start.strftime(DATE_FORMAT), "$lte": today_end.strftime(DATE_FORMAT)}
            # })


            shift_start_time = now.replace(hour=int(shift_times["start_time"].split(":")[0]),minute=int(shift_times["start_time"].split(":")[1]),second=int(shift_times["start_time"].split(":")[2]))
            shift_end_time = now.replace(hour=int(shift_times["end_time"].split(":")[0]),minute=int(shift_times["end_time"].split(":")[1]),second=int(shift_times["end_time"].split(":")[2]))

            

            query.append({
                "started_at": {"$gte": shift_start_time.strftime(DATE_FORMAT), "$lte": shift_end_time.strftime(DATE_FORMAT)}
            })

    if current_shift_check:
        current_shift = get_shift_for_time(now)
        print(f"current shift :: {current_shift}, sift time ranges :: {shift_time_ranges}")
      
        if current_shift and current_shift in shift_time_ranges:
            shift_times = shift_time_ranges[current_shift]
            # shift_start_time = now.replace(hour=int(shift_times["start_time"].split(":")[0]))
            # shift_end_time = now.replace(hour=int(shift_times["end_time"].split(":")[0]))
            # query.append({
            #     "started_at": {"$gte": shift_start_time.strftime(DATE_FORMAT), "$lte": shift_end_time.strftime(DATE_FORMAT)}
            # })


            shift_start_time = now.replace(hour=int(shift_times["start_time"].split(":")[0]),minute=int(shift_times["start_time"].split(":")[1]),second=int(shift_times["start_time"].split(":")[2]))
            shift_end_time = now.replace(hour=int(shift_times["end_time"].split(":")[0]),minute=int(shift_times["end_time"].split(":")[1]),second=int(shift_times["end_time"].split(":")[2]))

            

            query.append({
                "started_at": {"$gte": shift_start_time.strftime(DATE_FORMAT), "$lte": shift_end_time.strftime(DATE_FORMAT)}
            })


    # Handle date range queries
    if last_30_days_check:
        last_30_start = now - timedelta(days=30)
        query.append({"started_at": {"$gte": last_30_start.strftime(DATE_FORMAT), "$lte": now.strftime(DATE_FORMAT)}})

    if last_15_days_check:
        last_15_start = now - timedelta(days=15)
        query.append({"started_at": {"$gte": last_15_start.strftime(DATE_FORMAT), "$lte": now.strftime(DATE_FORMAT)}})

    if last_7_days_check:
        last_7_start = now - timedelta(days=7)
        query.append({"started_at": {"$gte": last_7_start.strftime(DATE_FORMAT), "$lte": now.strftime(DATE_FORMAT)}})


    # Add additional filters only if values are not None
    if part_name:
        query.append({"part_name": part_name})
    if batch_number:
        query.append({"batch_number": batch_number})
    if part_number:
        query.append({"part_number": part_number})
    if model_number:
        query.append({"model_number": model_number})
    if user:
        query.append({"user": user})

    # Handle time range filters
    if start_time and end_time:
        try:
            query.append({"started_at": {"$gte": start_time, "$lte": end_time}})
        except Exception:
            return "Invalid start_time or end_time format", {}, 400


    print(f"Query ::: {query}")
    # Database query
    insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)
    insp_col_data = list(insp_col.find({"$and": query}).sort("_id", -1)) if query else list(insp_col.find().sort("_id", -1))

    total_data = []
    for obj in insp_col_data:
        log_col = mongo_helper.read_collection(str(obj.get("_id")) + "_logs")
        log_col_data = list(log_col.find({"status": status}).sort("_id", -1)) if status else list(log_col.find().sort("_id", -1))
        total_data.extend(log_col_data)

    # Calculate overall counts
    ok_data = sum(1 for obj in total_data if obj.get("status") == "OK")
    nok_data = sum(1 for obj in total_data if obj.get("status") == "NOK")
    total_records = len(total_data)

    # Limit response size
    total_data = sorted(total_data, key=lambda x: x.get("_id"), reverse=True)

    ## inspection yield 
    inspection_yield = find_inspection_yield(ok_data,total_records)

    ## defect ppm
    defect_ppm = find_defect_ppm(nok_data,total_records)


    response = {
        "data": total_data,
        "ok_count": ok_data,
        "nok_count": nok_data,
        "total": total_records,
        "inspection_yield" : inspection_yield,
        "defect_ppm" : defect_ppm
    }

    return "Success", response, 200

def get_reports_util(data,download_required=False):
    print(f"payload :: {data}")
    
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    status = data.get("status", None)
    part_name = data.get("part_name", None)
    batch_number = data.get("batch_number", None)
    part_number = data.get("part_number", None)
    model_number = data.get("model_number", None)
    user = data.get("user", None)

    # Pagination logic
    page = int(data.get("page", 1))  # Default to page 1
    limit = int(data.get("limit", 5))  # Default limit to 50
    skip = (page - 1) * limit  # Calculate the number of documents to skip

    # Initialize query
    query = []
    now = datetime.now()
    
    # Get the report_type filters (today, yesterday, shifts, etc.)
    report_type = data.get("report_type", {})
    today_check = bool(report_type.get("today", False))
    yesterday_check = bool(report_type.get("yesterday", False))
    last_2_shifts_check = bool(report_type.get("last_2_shifts", False))
    last_3_shifts_check = bool(report_type.get("last_3_shifts", False))
    last_1_shifts_check = bool(report_type.get("last_1_shifts", False))
    current_shift_check = bool(report_type.get("current_shift", False))
    last_30_days_check = bool(report_type.get("last_30_days", False))
    last_15_days_check = bool(report_type.get("last_15_days", False))
    last_7_days_check = bool(report_type.get("last_7_days", False))

    # Date range handling
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    yesterday = now - timedelta(days=1)
    yesterday_start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_end = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

    # Add date filters based on report_type
    if today_check:
        query.append({"time_stamp": {"$gte": today_start.strftime(DATE_FORMAT), "$lte": today_end.strftime(DATE_FORMAT)}})
    if yesterday_check:
        query.append({"time_stamp": {"$gte": yesterday_start.strftime(DATE_FORMAT), "$lte": yesterday_end.strftime(DATE_FORMAT)}})

    # Handle shift-based filtering only if SHIFTS is defined
    if 'SHIFTS' in globals():
        shift_time_ranges = SHIFTS
    else:
        return "Error: Shift configuration missing", {}, 500
    

    current_shift = get_shift_for_time(now)  # Get current shift
    print(current_shift,"current shift")

    current_shift_times = shift_time_ranges.get(current_shift)
    print(f"current_shift_times :: {current_shift_times}")



    
    def get_shift_start_time(shift_times: dict, base_time: datetime) -> datetime:
        return base_time.replace(hour=int(shift_times["start_time"].split(":")[0]),
                                minute=int(shift_times["start_time"].split(":")[1]),
                                second=int(shift_times["start_time"].split(":")[2]))

    def get_shift_end_time(shift_times: dict, base_time: datetime) -> datetime:
        return base_time.replace(hour=int(shift_times["end_time"].split(":")[0]),
                                minute=int(shift_times["end_time"].split(":")[1]),
                                second=int(shift_times["end_time"].split(":")[2]))

    def is_within_current_shift(ts):
        if not current_shift_times:
            return False
        start = get_shift_start_time(current_shift_times, now)
        end = get_shift_end_time(current_shift_times, now)

        # Handle overnight shift (e.g., 22:00 to 06:00)
        if end < start:
            end += timedelta(days=1)

        return start <= ts <= end



    # Last 2 Shifts
    if last_2_shifts_check:
        if is_within_current_shift(now):
            # Current shift is active – shift the window back to before this shift started
            shift_start = get_shift_start_time(current_shift_times, now)
            last_2_start = shift_start - timedelta(hours=16)
            query.append({
                "time_stamp": {
                    "$gte": last_2_start.strftime(DATE_FORMAT),
                    "$lte": shift_start.strftime(DATE_FORMAT)
                }
            })
        else:
            # Current shift not active – normal case
            last_2_start = now - timedelta(hours=16)
            query.append({
                "time_stamp": {
                    "$gte": last_2_start.strftime(DATE_FORMAT),
                    "$lte": now.strftime(DATE_FORMAT)
                }
            })
   
    # Last 3 Shifts
    if last_3_shifts_check:
        if is_within_current_shift(now):
            # Current shift is active – shift the window back to before this shift started
            shift_start = get_shift_start_time(current_shift_times, now)
            last_3_start = shift_start - timedelta(hours=24)
            query.append({
                "time_stamp": {
                    "$gte": last_3_start.strftime(DATE_FORMAT),
                    "$lte": shift_start.strftime(DATE_FORMAT)
                }
            })
        else:
            # Current shift not active – normal case
            last_3_start = now - timedelta(hours=24)
            query.append({
                "time_stamp": {
                    "$gte": last_3_start.strftime(DATE_FORMAT),
                    "$lte": now.strftime(DATE_FORMAT)
                }
            })


    if last_1_shifts_check:
        last_shift_time = yesterday.replace(hour=23, minute=59, second=59)
        last_shift = get_shift_for_time(last_shift_time)
        last_shift = get_previous_shift()  # assuming this gets the previous shift

        if last_shift and last_shift in shift_time_ranges:
            shift_times = shift_time_ranges[last_shift]
            shift_start_time = now.replace(hour=int(shift_times["start_time"].split(":")[0]),
                                           minute=int(shift_times["start_time"].split(":")[1]),
                                           second=int(shift_times["start_time"].split(":")[2]))
            shift_end_time = now.replace(hour=int(shift_times["end_time"].split(":")[0]),
                                         minute=int(shift_times["end_time"].split(":")[1]),
                                         second=int(shift_times["end_time"].split(":")[2]))
            query.append({"time_stamp": {"$gte": shift_start_time.strftime(DATE_FORMAT), "$lte": shift_end_time.strftime(DATE_FORMAT)}})

    if current_shift_check:
        current_shift = get_shift_for_time(now)
        if current_shift and current_shift in shift_time_ranges:
            shift_times = shift_time_ranges[current_shift]
            shift_start_time = now.replace(hour=int(shift_times["start_time"].split(":")[0]),
                                           minute=int(shift_times["start_time"].split(":")[1]),
                                           second=int(shift_times["start_time"].split(":")[2]))
            shift_end_time = now.replace(hour=int(shift_times["end_time"].split(":")[0]),
                                         minute=int(shift_times["end_time"].split(":")[1]),
                                         second=int(shift_times["end_time"].split(":")[2]))
            query.append({"time_stamp": {"$gte": shift_start_time.strftime(DATE_FORMAT), "$lte": shift_end_time.strftime(DATE_FORMAT)}})

    # Handle last 30, 15, and 7 days
    if last_30_days_check:
        last_30_start = now - timedelta(days=30)
        query.append({"time_stamp": {"$gte": last_30_start.strftime(DATE_FORMAT), "$lte": now.strftime(DATE_FORMAT)}})

    if last_15_days_check:
        last_15_start = now - timedelta(days=15)
        query.append({"time_stamp": {"$gte": last_15_start.strftime(DATE_FORMAT), "$lte": now.strftime(DATE_FORMAT)}})

    if last_7_days_check:
        last_7_start = now - timedelta(days=7)
        query.append({"time_stamp": {"$gte": last_7_start.strftime(DATE_FORMAT), "$lte": now.strftime(DATE_FORMAT)}})

    # Add filters for part_name, batch_number, part_number, model_number, user, status
    if part_name:
        query.append({"part_name": part_name})
    if batch_number:
        query.append({"batch_number": batch_number})
    if part_number:
        query.append({"part_number": part_number})
    if model_number:
        query.append({"model_number": model_number})
    if user:
        query.append({"user": user})
    if status:
        query.append({"status": status})

    # Handle time range filters
    if start_time and end_time:
        try:
            query.append({"time_stamp": {"$gte": start_time, "$lte": end_time}})
        except Exception:
            return "Invalid start_time or end_time format", {}, 400

    print(f"Query ::: {query}")

    # Fetch data from MongoDB with pagination
    insp_col = mongo_helper.read_collection(TOTAL_LOGS)
    # insp_col_data = list(insp_col.find({"$and": query}).skip(skip).limit(limit).sort("_id", -1))
    insp_col_data = list(insp_col.find({"$and": query}).sort("_id", -1))


    # Calculate counts and metrics
    ok_data = sum(1 for obj in insp_col_data if obj.get("status") == "OK")
    nok_data = sum(1 for obj in insp_col_data if obj.get("status") == "NOK")
    rework_data = sum(1 for obj in insp_col_data if obj.get("status") == "REWORK")

    total_records = len(insp_col_data)

    # Calculate inspection yield and defect ppm
    inspection_yield = find_inspection_yield(ok_data, total_records)
    defect_ppm = find_defect_ppm(nok_data, total_records)

    if download_required is True:
        insp_col_data = insp_col_data
    else:
        insp_col_data = insp_col_data[skip:skip+limit]
    # Prepare response
    response = {
        "data": insp_col_data,
        "ok_count": ok_data,
        "nok_count": nok_data,
        "rework_count": rework_data,
        "total": total_records,
        "inspection_yield": inspection_yield,
        "defect_ppm": defect_ppm,
        "page": page,
        "limit": limit,
        "total_pages": (total_records // limit) + (1 if total_records % limit > 0 else 0)
    }

    return "Success", response, 200

# def get_latest_reports_util(data):
#     user = data.get("user")
#     # print(user)
#     insp_col = mongo_helper.read_collection("inspection")
#     limit = 5
    
    
#     if user:
#         insp_col_data = [i for i in insp_col.find({"user":user}).sort("_id", -1)]
#         print(insp_col_data)
#     else:
#         insp_col_data = [i for i in insp_col.find().sort("_id", -1)]

#     total_data = []
#     for obj in insp_col_data:
#         id = obj.get("_id")
#         log_col = mongo_helper.read_collection(str(id) + "_logs")
#         log_col_data = [i for i in log_col.find().sort("_id", -1).limit(limit)]
#         total_data.extend(log_col_data)
#         if len(total_data) >= limit:
#             break
#     total_data = total_data[:limit]
#     # print("*********************************************")
#     # print(total_data)

#     total_col = mongo_helper.read_collection(TOTAL_INSPECTIONS)

#     if user:
#         total_col_data = total_col.find_one({'user':user})
#         print("------------------------------")
#         print(total_col_data)
#         total_ok_count = total_col_data.get("OK")
#         total_nok_count = total_col_data.get("NOK")

#     else:
#         total_col_data = [i for i in total_col.find()]
#         total_ok_count = 0
#         total_nok_count = 0
#         for obj in total_col_data:
#             # print(obj,"objjjjjjjjjj")
#             total_ok_count += obj.get("OK")
#             total_nok_count += obj.get("NOK")

#      ## inspection yield 
#     inspection_yield = find_inspection_yield(total_ok_count, total_ok_count + total_nok_count)
#      ## defect ppm
#     defect_ppm = find_defect_ppm(total_nok_count, total_ok_count + total_nok_count)



#     response = {
#         "data": total_data,
#         "ok_count":total_ok_count ,
#         "nok_count": total_nok_count,
#         "total": total_ok_count + total_nok_count,
#         "inspection_yield" : inspection_yield,
#         "defect_ppm" : defect_ppm
#         # "page": 0,
#         # "per_page": 0,
#         # "total_pages": (total_records + per_page - 1) // per_page  # Calculate total pages
#     }
    
    
#     return "Success", response, 200







def get_latest_reports_util(data):
    user = data.get("user")
    insp_col = mongo_helper.read_collection("inspection")
    limit = 5
    
    all_users = set()
    all_part_numbers = set()
    
    # Fetch all users and part numbers from the entire collection
    all_insp_col_data = insp_col.find()
    for obj in all_insp_col_data:
        all_users.add(obj.get("user"))
        all_part_numbers.add(obj.get("part_number"))
    



    total_log_col = mongo_helper.read_collection(TOTAL_LOGS)
    if user:
        # insp_col_data = [i for i in insp_col.find({"user": user}).sort("_id", -1)]
        insp_col_data = [i for i in total_log_col.find({"user": user}).limit(limit).sort("_id", -1)]
    else:
        # insp_col_data = [i for i in insp_col.find().sort("_id", -1)]
        insp_col_data = [i for i in total_log_col.find().limit(limit).sort("_id", -1)]

    
    # total_data = []
    # for obj in insp_col_data:
    #     id = obj.get("_id")
    #     log_col = mongo_helper.read_collection(str(id) + "_logs")
    #     log_col_data = [i for i in log_col.find().sort("_id", -1).limit(limit)]
    #     total_data.extend(log_col_data)
    #     if len(total_data) >= limit:
    #         break
    total_data = insp_col_data

    total_col = mongo_helper.read_collection(TOTAL_INSPECTIONS)

    if user:
        total_col_data = total_col.find_one({'user': user})
        total_ok_count = total_col_data.get("OK", 0) if total_col_data else 0
        total_nok_count = total_col_data.get("NOK", 0) if total_col_data else 0
        total_rework_count = total_col_data.get("REWORK", 0) if total_col_data else 0

    else:
        total_col_data = [i for i in total_col.find()]
        total_ok_count = sum(obj.get("OK", 0) for obj in total_col_data)
        total_nok_count = sum(obj.get("NOK", 0) for obj in total_col_data)
        total_rework_count = sum(obj.get("REWORK", 0) for obj in total_col_data)



    ## inspection yield 
    inspection_yield = find_inspection_yield(total_ok_count, total_ok_count + total_nok_count)
    ## defect ppm
    defect_ppm = find_defect_ppm(total_nok_count, total_ok_count + total_nok_count)

    response = {
        "data": total_data,
        "user": user,  # Retaining user if provided
        "all_users": list(all_users),  # Ensuring all unique users are collected from full dataset
        "all_part_numbers": list(all_part_numbers),  # Ensuring all unique part numbers are collected from full dataset
        "ok_count": total_ok_count,
        "nok_count": total_nok_count,
        "rework_count": total_rework_count,
        "total": total_ok_count + total_nok_count + total_rework_count,
        "inspection_yield": inspection_yield,
        "defect_ppm": defect_ppm
    }
    
    return "Success", response, 200



from concurrent.futures import ThreadPoolExecutor
from pymongo import DESCENDING
from bson import ObjectId

# def get_reports_util(data):
# 	start_time = data.get("start_time")
# 	end_time = data.get("end_time")
# 	status = data.get("status")
# 	part_name = data.get("part_name")
# 	batch_number = data.get("batch_number")
# 	part_number = data.get("part_number")
# 	model_number = data.get("model_number")
# 	user = data.get("user")

# 	query = {}
# 	if part_name:
# 		query["part_name"] = part_name
# 	if batch_number:
# 		query["batch_name"] = batch_number
# 	if part_number:
# 		query["part_number"] = part_number
# 	if model_number:
# 		query["model_number"] = model_number
# 	if user:
# 		query["user"] = user
# 	if start_time and end_time:
# 		query["started_at"] = {"$gte": start_time, "$lte": end_time}

# 	insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)

# 	# ✅ Fetch the last 10 inspections OR all filtered results
# 	pipeline = [
# 		{"$match": query},
# 		{"$sort": {"_id": -1}},
# 		# {"$limit": 2},
# 		{"$project": {  # Fetch all necessary fields
# 			"_id": 1,
# 			"part_name": 1,
# 			"batch_name": 1,
# 			"part_number": 1,
# 			"model_number": 1,
# 			"user": 1,
# 			"started_at": 1,
# 			"ended_at": 1,
# 			"shift": 1
# 		}}
# 	]
    
# 	insp_col_data = list(insp_col.aggregate(pipeline))
# 	inspections = {str(i["_id"]): i for i in insp_col_data}  # Convert to dict for easy lookup

# 	if not inspections:
# 		return "Success", {"data": [], "ok_count": 0, "nok_count": 0, "total": 0}, 200

# 	# ✅ Fetch logs dynamically from respective collections
# 	def fetch_logs(inspection_id):
# 		log_col = mongo_helper.read_collection(f"{inspection_id}_logs")  # Query correct log collection
# 		log_query = {"status": status} if status else {}

# 		return list(log_col.find(log_query, {"_id": 0, "status": 1, "defects": 1, "predicted_images": 1}).sort("_id", DESCENDING))


# 	ok_count = 0
# 	nok_count = 0

# 	# ✅ Parallel log fetching
# 	with ThreadPoolExecutor() as executor:
# 		results = list(executor.map(fetch_logs, inspections.keys()))

# 	# ✅ Map logs to inspections
# 	x = []
# 	print(inspections)
# 	for idx, (inspection_id, log_data) in enumerate(zip(inspections.keys(), results)):
# 		# d = log_data
# 		# print(d,"dddd")
# 		# input("Enter :::")
# 		# inspections[inspection_id]["logs"] = log_data
# 		inspections[inspection_id]["logs"] = log_data
# 		# ins_data = inspections[inspection_id]
# 		# d.update(ins_data)
    

# 		x.append(log_data)

# 		ok_count += sum(1 for obj in log_data if obj.get("status") == "OK")
# 		nok_count += sum(1 for obj in log_data if obj.get("status") == "NOK")

# 	response = {
# 		"data": list(inspections.values()),  # Convert dict back to list
# 		# "data" : x,
# 		"ok_count": ok_count,
# 		"nok_count": nok_count,
# 		"total": ok_count + nok_count
# 	}

# 	return "Success", response, 200





def save_data_as_csv(total_data, reports_folder_path):
    MAX_CSV_SIZE_MB = 25
    MAX_CSV_SIZE_BYTES = MAX_CSV_SIZE_MB * 1024 * 1024

    os.makedirs(reports_folder_path, exist_ok=True)

    # Prepare to write multiple files if needed
    file_index = 1
    total_size = 0
    file_paths = []

    for chunk_start in range(0, len(total_data), 10000):  # Process data in chunks
        chunk = total_data[chunk_start:chunk_start + 10000]
        df = pd.DataFrame(chunk)

        while True:  # Save until it fits within the size limit
            bson_id = str(bson.ObjectId())
            csv_path = os.path.join(reports_folder_path, f'{bson_id}_{file_index}.csv')
            df.to_csv(csv_path, index=False)

            file_size = os.path.getsize(csv_path)
            if file_size <= MAX_CSV_SIZE_BYTES:
                file_paths.append(csv_path)
                total_size += file_size
                break  # Successfully saved this chunk

            # If file is too big, split it
            file_index += 1

    # Create a zip file whether it's a single file or multiple files
    zip_path = os.path.join(reports_folder_path, 'report_files.zip')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in file_paths:
            zipf.write(file_path, os.path.basename(file_path))
            os.remove(file_path)  # Delete original file after zipping
    
    return zip_path







def download_report_util_running(data):

    start_time = data.get("start_time")
    end_time = data.get("end_time")
    status = data.get("status")
    part_name = data.get("part_name")
    batch_number = data.get("batch_number")
    part_number = data.get("part_number")
    model_number = data.get("model_number")
    user = data.get("user")


    query = []
    if part_name:
        query.append({"part_name": part_name})
    if batch_number:
        query.append({"batch_name": batch_number})
    if part_number:
        query.append({"part_number": part_number})
    if model_number:
        query.append({"model_number": model_number})
    if user:
        query.append({"user": user})

    if start_time and end_time:
        try:
            query.append({"started_at": {"$gte": start_time, "$lte": end_time}})
        except ValueError:
            return "Invalid start_time or end_time format", {}, 400

    insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)

    if query:
        insp_col_data = [i for i in insp_col.find({"$and": query}).sort("_id", -1)]
    else:
        insp_col_data = [i for i in insp_col.find().sort("_id", -1)]

    total_data = []
    for obj in insp_col_data:
        id = obj.get("_id")
        log_col = mongo_helper.read_collection(str(id) + "_logs")
        if status:
            log_col_data = [i for i in log_col.find({"status": status}).sort("_id", -1)]
        else:
            log_col_data = [i for i in log_col.find().sort("_id", -1)]
        total_data.extend(log_col_data)


    print(len(total_data))
    df = pd.DataFrame(total_data)
    reports_folder_path = os.path.join(os.path.join(BUCKET_PATH,"reports"))
    os.makedirs(reports_folder_path,exist_ok=True)
    bson_id = str(bson.ObjectId())
    csv_path = os.path.join(reports_folder_path,bson_id)+".csv"

    print(csv_path,"csv path")

    df.to_csv(csv_path)



    return "Success", {"csv_file":csv_path.replace(BUCKET_PATH,"http://localhost:3307"),"file_name":bson_id+".csv"}, 200








def download_report_util_pending(data):
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    status = data.get("status")
    part_name = data.get("part_name")
    batch_number = data.get("batch_number")
    part_number = data.get("part_number")
    model_number = data.get("model_number")
    user = data.get("user")

    query = {}
    if part_name:
        query["part_name"] = part_name
    if batch_number:
        query["batch_name"] = batch_number
    if part_number:
        query["part_number"] = part_number
    if model_number:
        query["model_number"] = model_number
    if user:
        query["user"] = user

    if start_time and end_time:
        try:
            query["started_at"] = {"$gte": start_time, "$lte": end_time}
        except ValueError:
            return "Invalid start_time or end_time format", {}, 400

    insp_col = mongo_helper.read_collection(INSPECTION_COLLECTION)
    
    # Fetch all documents with a single query
    insp_col_data = list(insp_col.find(query).sort("_id", DESCENDING))
    
    total_data = []
    reports_folder_path = os.path.join(os.path.join(BUCKET_PATH, "reports"))
    os.makedirs(reports_folder_path, exist_ok=True)
    bson_id = str(bson.ObjectId())
    csv_path = os.path.join(reports_folder_path, bson_id) + ".csv"

    # Use ThreadPoolExecutor to fetch logs concurrently
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_log = {executor.submit(fetch_logs, obj["_id"], status): obj["_id"] for obj in insp_col_data}

        for future in as_completed(future_to_log):
            log_data = future.result()
            total_data.extend(log_data)
    
    # Directly create DataFrame from the fetched data
    if total_data:
        df = pd.DataFrame(total_data)
        df.to_csv(csv_path, index=False)
    else:
        return "No data found", {}, 404

    return "Success", {"csv_file": csv_path.replace(BUCKET_PATH, "http://localhost:3307"), "file_name": bson_id + ".csv"}, 200


def fetch_logs(document_id, status):
    """Fetch logs from the logs collection related to the document_id."""
    log_col = mongo_helper.read_collection(str(document_id) + "_logs")
    if status:
        log_col_data = list(log_col.find({"status": status}).sort("_id", DESCENDING))
    else:
        log_col_data = list(log_col.find().sort("_id", DESCENDING))
    return log_col_data



def download_report_util(data):
    download_required = True
    message, resp, status_code = get_reports_util(data,download_required)

    total_data = resp.get("data",[])

    print(f"length of total data :: {len(total_data)}")


    df = pd.DataFrame(total_data)
    reports_folder_path = os.path.join(os.path.join(BUCKET_PATH,"reports"))
    os.makedirs(reports_folder_path,exist_ok=True)
    bson_id = str(bson.ObjectId())
    csv_path = os.path.join(reports_folder_path,bson_id)+".csv"

    print(csv_path,"csv path")

    df.to_csv(csv_path)



    return "Success", {"csv_file":csv_path.replace(BUCKET_PATH,"http://localhost:3307"),"file_name":bson_id+".csv","total":len(total_data)}, 200










def convert_image_to_bytes(image_path):
    try:     
        image_path= image_path.replace("http://localhost:3307", BUCKET_PATH)
        with open(image_path, "rb") as image_file:
            # Read the file and encode it to Base64
            encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
            return encoded_image
    except FileNotFoundError:
        print(f"File not found: {image_path}")
        return None


def get_pdf(data):
    # path_to_wkhtmltopdf = r"/home/alpha/Downloads/wkhtmltox_0.12.5-1.bionic_amd64.deb"  # Adjust to the correct path
    # config = pdfkit.configuration(wkhtmltopdf=path_to_wkhtmltopdf)
    path_to_wkhtmltopdf = "/usr/bin/wkhtmltopdf"
    config = pdfkit.configuration(wkhtmltopdf=path_to_wkhtmltopdf)
    template_loader = jinja2.FileSystemLoader(searchpath="./")  # Adjust path if necessary
    template_env = jinja2.Environment(loader=template_loader)
    template = template_env.get_template("template.html")
    # Render the HTML
    predicted_images= data.get('predicted_images')
    print("...'P", predicted_images)
 
    predicted_images_bytes = [convert_image_to_bytes(image[0]) for image in predicted_images]
 
    input_images= data.get('input_images')
    input_images_bytes_bytes = [convert_image_to_bytes(image[0]) for image in input_images]
    
 
    data["input_images"] = input_images_bytes_bytes
    data["predicted_images"] = predicted_images_bytes
 
    output_html = template.render(
        data = data
    )

    # Save the rendered HTML to a file
    html_file = "report.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(output_html)

    print(f"HTML report generated as '{html_file}'.")

    # Convert the saved HTML to a PDF using pdfkit
    # pdf_file = r"C:\factree\projects-be\Bucket\report.pdf"
    pdf_file = os.path.join(BUCKET_PATH,str(bson.ObjectId())+".pdf")
    # print(f"pdf file path :: {pdf_file}")
    pdfkit.from_file(html_file, pdf_file,configuration=config)
    pdf_file= pdf_file.replace(BUCKET_PATH, "http://localhost:3307")
 
    print("pdf file returned successfully !!!",pdf_file)
    return pdf_file



def download_view_detail_util(data):
    inspction_id = data.get("inspection_id")
    id = data.get("_id")
    print("..........", data)
    log_col = mongo_helper.read_collection(TOTAL_LOGS)
    log_col_data = log_col.find_one({"_id":bson.ObjectId(id),"inspection_id":inspction_id})
    print("log col data",log_col_data)
    
    pdf_file= get_pdf(log_col_data)
    

    return "success",{"pdf_file":pdf_file},200




def zip_files(file_paths, zip_filename):
    """Compresses given files into a zip archive."""
    zip_path = os.path.join(os.path.dirname(file_paths[0]), zip_filename)
    
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in file_paths:
            zipf.write(file, os.path.basename(file))  # Store only filename in zip
    
    return zip_path




def send_email_threaded(sender_email, receiver_email, password, subject, body, files):
    """Function to send an email with attachments in a separate thread"""

    # Create email message (Ensure this is MIMEMultipart, NOT a string)
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = receiver_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    print(len(files))
    if len(files) == 1 and files[0].endswith(".pdf"):

        files = files
        print("fielssssssssssssss")
        
    else:
        # Attach files
        zip_path = zip_files(files, "REPORTS.zip")  # Compress file
        files = [zip_path]  # Attach the ZIP instead of raw files

    print(f"files ::: {files}")

    # Attach files
    for file in files:
        try:
            with open(file, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())

            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(file)}")
            message.attach(part)
        except Exception as e:
            print(f"Error attaching file {file}: {e}")

    # Send the email
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, message.as_string())
        print(f"Email sent successfully to {receiver_email} with attachments!")
    except Exception as e:
        print(f"SMTP Error: {e}")

def send_mail_util(data):
    """ Function to send an email asynchronously """
    
    receiver_email = data.get("receiver_email")
    if not receiver_email:
        return "Error: No recipient email provided", {}, 400  # Return error if email is missing
    # Create email
    subject = "Factree.Ai Email With Reports Attached"
    
    body = f"Hello User ,\n\nPlease find the attached file .\n\nBest Regards,\nfactree.ai"


    
    message, resp, status_code = download_report_util(data)
    csv_path = resp.get("csv_file")

    print(csv_path, "csv path")
    csv_path_local = os.path.join(BUCKET_PATH, "reports", os.path.basename(csv_path))
    print(csv_path_local, "csv path local")

    # Ensure the file exists before attaching
    if not os.path.exists(csv_path_local):
        return f"Error: File not found at {csv_path_local}", {}, 400

    # # Email details
    # subject = "Test Email with CSV and PDF Attachments"
    # body = "Hello,\n\n Please find the attached CSV and PDF files.\n\nBest Regards,\nYour Name"

    # Attach files
    files = [csv_path_local]

    # Start email sending in a new thread
    email_thread = threading.Thread(target=send_email_threaded, args=(SENDER_EMAIL, receiver_email, SENDER_EMAIL_PASSWORD, subject, body, files))
    email_thread.start()

    return f"Email is being sent to {receiver_email} in the background.", {}, 200
   


def send_pdf_mail_util(data):
    message, resp, status_code = download_view_detail_util(data)
    pdf_file = resp.get("pdf_file")
    # http://localhost:3307\\67b5ed7a5269e417e7b78bf5.pdf
    pdf_file_local = pdf_file.replace("http://localhost:3307",BUCKET_PATH)

    receiver_email = data.get("receiver_email")
    if not receiver_email:
        return "Error: No recipient email provided", {}, 400  # Return error if email is missing
    # Create email
    subject = "Factree.Ai Email With Reports Attached"
    body = f"Hello User ,\n\nPlease find the attached  Report.Zip .\n\nBest Regards,\nfactree.ai"



    # Ensure the file exists before attaching
    if not os.path.exists(pdf_file_local):
        return f"Error: File not found at {pdf_file_local}", {}, 400
    

    # # Email details
    # subject = "Test Email with CSV and PDF Attachments"
    # body = "Hello,\n\n Please find the attached CSV and PDF files.\n\nBest Regards,\nYour Name"

    # Attach files
    files = [pdf_file_local]

    # Start email sending in a new thread
    email_thread = threading.Thread(target=send_email_threaded, args=(SENDER_EMAIL, receiver_email, SENDER_EMAIL_PASSWORD, subject, body, files))
    email_thread.start()


    return "success",{"pdf_file":pdf_file_local},200


    
    

    


