import basler_module
import cv2
from main_helper import *
from datetime import datetime
import bson
import os
import time
import threading

trigger_lock = threading.Lock()
dict_lock = threading.Lock()
camera_lock = threading.Lock()

redis_helper = RedisHelper()
mongo_helper = MongoDBHelper()

cameras = []
master = None
last_camera_ids = None



# connector = basler_module.basler_camera_connector()

# # Retrieve the list of connected cameras
# connected_cameras = connector.cameras_info

# if not connected_cameras:
#     print("No cameras connected.")
# else:
#     print(f"Found {len(connected_cameras)} connected camera(s):")
#     for cam in connected_cameras:
#         print(
#             f"Serial: {cam['serial_number']}, Model: {cam['model_name']}, "
#             f"Resolution: {cam['width']}x{cam['height']}, Friendly Name: {cam['friendly_name']}"
#         )

# # Optionally push the list to Redis
# redis_helper.push_data("connected_cameras", connected_cameras)



def list_connected_cameras():
    connector = basler_module.basler_camera_connector()

    # Retrieve the list of connected cameras
    connected_cameras = connector.cameras_info

    if not connected_cameras:
        print("No cameras connected.")
    else:
        print(f"Found {len(connected_cameras)} connected camera(s):")
        for cam in connected_cameras:
            print(
                f"Serial: {cam['serial_number']}, Model: {cam['model_name']}, "
                f"Resolution: {cam['width']}x{cam['height']}, Friendly Name: {cam['friendly_name']}"
            )

    # Optionally push the list to Redis
    redis_helper.push_data("connected_cameras", connected_cameras)

    return connected_cameras



def imwriter(path, image):
    try:
        cv2.imwrite(path, image)
    except Exception as e:
        print("Image write failed:", e)


def capture_image(cam):
    try:
        with trigger_lock:
            cam.camera.ExecuteSoftwareTrigger()

        time.sleep(0.02)
        return cam.get_image()

    except Exception as e:
        print(f"Camera {cam.serial_number} capture error:", e)
        return None


def initialize_cameras(camera_details, mode):
    global cameras, master

    print("Reinitializing cameras")
    print("Mode:", mode)

    # cleanup existing cameras
    if cameras:
        for cam in cameras:
            try:
                cam.close()  # if SDK supports it
            except:
                pass

    cameras = []
    master = basler_module.basler_camera_master()

    for cam_cfg in camera_details:
        try:
            serial = cam_cfg["serial_number"]
            aoi = cam_cfg.get("aoi")

            cam = basler_module.basler_camera_individual(
                master,
                serial,
                mode,
                aoi
            )

       

            cameras.append(cam)
            print(f"Camera {serial} ready | AOI: {aoi}")

        except Exception as e:
            print(f"Failed to init camera {cam_cfg}:", e)

    print("Active cameras:", [c.serial_number for c in cameras])
    save_running_cameras(camera_details,mode)
    time.sleep(0.5)


def camera_config_watcher():
    global last_camera_ids

    print("Camera config watcher started")

    while True:
        config = redis_helper.pull_data("camera_config")

        if not config or not isinstance(config, dict):
            time.sleep(0.1)
            continue

        camera_details = config.get("camera_details")
        mode = config.get("mode", "SOFTWARE")

        if not camera_details or not isinstance(camera_details, list):
            time.sleep(0.1)
            continue

        # extract serial numbers for change detection
        camera_ids = [c["serial_number"] for c in camera_details]

        # if camera_ids != last_camera_ids:
        if camera_ids:

            with camera_lock:
                initialize_cameras(camera_details, mode)
                last_camera_ids = camera_ids.copy()

            redis_helper.push_data("camera_config", None)

        time.sleep(0.1)



def save_capture_data(data):
    mongo_helper.read_collection(DATA).insert_one({
        "capture_id": data["capture_id"],
        "captured_at": data["captured_at"],
        "captured_images": data["captured_images"]
    })
    print(f"Saved capture {data['capture_id']}")


def save_running_cameras(camera_details, mode):
    mongo_helper.read_collection(RUNNING_CAMERAS).update_one(
        {},  # single document
        {
            "$set": {
                "camera_details": camera_details,
                "mode": mode,
                "started_at": datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
            }
        },
        upsert=True
    )

    print("Running cameras state saved")



def camera_list_scheduler():
    try:
        list_connected_cameras()
    except Exception as e:
        print("Error listing cameras:", e)
    # while True:
    #     try:
    #         list_connected_cameras()
    #     except Exception as e:
    #         print("Error listing cameras:", e)
    #     time.sleep(5)  # wait 5 seconds before next check

# Start the thread
threading.Thread(
    target=camera_list_scheduler,
    daemon=True
).start()


# threading.Thread(
#     target=list_connected_cameras,
#     daemon=True
# ).start()


threading.Thread(
    target=camera_config_watcher,
    daemon=True
).start()



print("Multi-camera capture service started")

while True:
    trigger = redis_helper.pull_data("capture_trigger")

    if trigger != "capture":
        time.sleep(0.05)
        continue

    redis_helper.push_data("capture_trigger", None)
    print("Capture triggered")

    capture_id = str(bson.ObjectId())
    captured_images = {}

    def capture_worker(cam):
        print(f"Triggering camera {cam.serial_number}")
        img = capture_image(cam)

        if img is None:
            print(f"No image from camera {cam.serial_number}")
            return

        with dict_lock:
            captured_images[cam.serial_number] = img

    with camera_lock:
        if not cameras:
            print("No cameras available")
            continue

        threads = []
        for cam in cameras:
            t = threading.Thread(target=capture_worker, args=(cam,))
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

    if not captured_images:
        print("No images captured")
        continue

    today = datetime.now().strftime("%Y_%m_%d")
    hour = datetime.now().strftime("%H")
    save_dir = os.path.join(BUCKET_PATH, today, hour)
    os.makedirs(save_dir, exist_ok=True)

    image_urls = []

    def save_worker(cam_id, img):
        file_id = str(bson.ObjectId())
        file_path = os.path.join(save_dir, f"{cam_id}_{file_id}.jpg")
        imwriter(file_path, img)

        url = file_path.replace(BUCKET_PATH, "http://localhost:3307")
        with dict_lock:
            image_urls.append(url)

    threads = []
    for cam_id, img in captured_images.items():
        t = threading.Thread(target=save_worker, args=(cam_id, img))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    save_capture_data({
        "capture_id": capture_id,
        "captured_at": datetime.now().strftime("%Y_%m_%d_%H_%M_%S"),
        "captured_images": image_urls
    })

    print(f"Capture complete | Images saved: {len(image_urls)}")

