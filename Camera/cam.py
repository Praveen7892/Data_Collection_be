
import basler_module
import cv2
from main_helper import *
from datetime import datetime
import bson
import os
import time
import threading


def imwriter(path, image):
    try:
        if image is not None:
            cv2.imwrite(path, image)
    except Exception as e:
        print("Image write failed:", e)

def capture_image(cam):
    try:
        # SOFTWARE trigger is REQUIRED
        cam.camera.ExecuteSoftwareTrigger()

        img = cam.get_image()
        if img is None:
            return None

        return img

    except Exception as e:
        cam_id = getattr(cam, "serial_number", "UNKNOWN")
        print(f"Camera {cam_id} capture error:", e)
        return None


redis_helper = RedisHelper()
mongo_helper = MongoDBHelper()

redis_helper.push_data("capture_trigger", None)

curr_insp_col = mongo_helper.read_collection(DATA)

master = basler_module.basler_camera_master()

camera_ids = ["40532056"]  

cameras = [
    basler_module.basler_camera_individual(master, cid, "SOFTWARE")
    for cid in camera_ids
]

print("Multi-camera capture service started")


def save_capture_data_util(data):
    doc = {
        "capture_id": str(data["capture_id"]),
        "captured_at": data["captured_at"],
        "captured_images": data["captured_images"],
    }

    mongo_helper.read_collection(DATA).insert_one(doc)
    print(f"Saved inspection {data['capture_id']} | Images: {len(data['captured_images'])}")


lock = threading.Lock()

while True:

    capture_trigger = redis_helper.pull_data("capture_trigger")

    if capture_trigger not in (True, "capture"):
        time.sleep(0.05)
        continue

    redis_helper.push_data("capture_trigger", None)

    current_capture_id = str(bson.ObjectId())
    print("Capture triggered")

    captured_images_dict = {}
    threads = []

    def capture_and_store(cam):
        img = capture_image(cam)
        if img is not None:
            cam_id = cam.serial_number  
            with lock:
                captured_images_dict[cam_id] = img

    for cam in cameras:
        t = threading.Thread(target=capture_and_store, args=(cam,))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    if not captured_images_dict:
        print("No images captured")
        continue

    captured_at = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    # Get current date and hour
    today = datetime.now().strftime("%Y_%m_%d")   # e.g., 2026_01_27
    hour = datetime.now().strftime("%H")  
    
    save_path = os.path.join(BUCKET_PATH, today, hour)
    os.makedirs(save_path, exist_ok=True)

    captured_image_urls = []
    threads = []

    def save_image(cam_id, img):
        bson_id = str(bson.ObjectId())
        file_path = os.path.join(save_path, f"{cam_id}_{bson_id}.jpg")
        imwriter(file_path, img)

        url = file_path.replace(BUCKET_PATH, "http://localhost:3307")
        with lock:
            captured_image_urls.append(url)

    for cam_id, img in captured_images_dict.items():
        t = threading.Thread(target=save_image, args=(cam_id, img))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    result_data = {
        "capture_id": current_capture_id,
        "captured_images": captured_image_urls,
        "captured_at": captured_at
    }

    save_capture_data_util(result_data)
    print(f"Capture complete | Images saved: {len(captured_image_urls)}")
