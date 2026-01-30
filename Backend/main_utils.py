from main_helper import MongoDBHelper, RedisHelper
from constants import *
from bson import ObjectId



mongo_helper = MongoDBHelper()
redis_helper = RedisHelper()



def get_cameras_utils ():
    cameras = redis_helper.pull_data("cameras")
    print(cameras, ":::: cameras :::")

    return "cameras", cameras, 200

def get_running_cameras_utils():
    running_col = mongo_helper.read_collection(RUNNING_CAMERAS)
    running_col_data = running_col.find_one(sort=[("_id", -1)])

    if running_col_data and "_id" in running_col_data:
        running_col_data["_id"] = str(running_col_data["_id"])

    print(running_col_data, "running_col_data")

    return "success", running_col_data, 200

def initialization_utils(data):
     print(data,":::: data")

     cameras = data["cameras"]
     mode = data["mode"]
     print(mode, ">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>> mode ")

     camera_details = [
        {
            "serial_number": cam["serial_number"],
            "aoi": cam.get("aoi")
        }
        for cam in cameras
        if "serial_number" in cam
     ]

     redis_helper.push_data("camera_config",{
          "camera_details": camera_details,
          "mode": mode
     })

     return "success", {}, 200


def capture_util(data):
	capture = data.get("capture")

	redis_helper.push_data("capture_trigger","capture")

	
	return "captured", {}, 200



def get_captured_images_util():
    capture_col = mongo_helper.read_collection(DATA)
    capture_col_data = capture_col.find_one(sort=[("_id", -1)])

    if capture_col_data and "_id" in capture_col_data:
        capture_col_data["_id"] = str(capture_col_data["_id"])

    print(capture_col_data, "capture_col_data")

    return "captured", capture_col_data, 200


