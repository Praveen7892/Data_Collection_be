from main_helper import MongoDBHelper, RedisHelper
from constants import *
from bson import ObjectId



mongo_helper = MongoDBHelper()
redis_helper = RedisHelper()



def get_cameras_utils ():
    cameras = redis_helper.pull_data("cameras")
    print(cameras, ":::: cameras :::")

    return "cameras", cameras, 200
    


def capture_util(data):
	capture = data.get("capture")

	redis_helper.push_data("capture_trigger",capture)

	
	return "captured", {}, 200



def get_captured_images_util():
    capture_col = mongo_helper.read_collection(DATA)
    capture_col_data = capture_col.find_one(sort=[("_id", -1)])

    if capture_col_data and "_id" in capture_col_data:
        capture_col_data["_id"] = str(capture_col_data["_id"])

    print(capture_col_data, "capture_col_data")

    return "captured", capture_col_data, 200


