
# import basler_module
# import cv2
# from main_helper import *
# from datetime import datetime
# import bson
# import os
# import time
# import threading


# def imwriter(path, image):
#     try:
#         if image is not None:
#             cv2.imwrite(path, image)
#     except Exception as e:
#         print("Image write failed:", e)

# def capture_image(cam):
#     try:
#         # SOFTWARE trigger is REQUIRED
#         cam.camera.ExecuteSoftwareTrigger()

#         img = cam.get_image()
#         if img is None:
#             return None

#         return img

#     except Exception as e:
#         cam_id = getattr(cam, "serial_number", "UNKNOWN")
#         print(f"Camera {cam_id} capture error:", e)
#         return None


# redis_helper = RedisHelper()
# mongo_helper = MongoDBHelper()

# redis_helper.push_data("capture_trigger", None)

# curr_insp_col = mongo_helper.read_collection(DATA)

# master = basler_module.basler_camera_master()

# camera_ids = ["40532056"]  

# cameras = [
#     basler_module.basler_camera_individual(master, cid, "SOFTWARE")
#     for cid in camera_ids
# ]

# print("Multi-camera capture service started")


# def save_capture_data_util(data):
#     doc = {
#         "capture_id": str(data["capture_id"]),
#         "captured_at": data["captured_at"],
#         "captured_images": data["captured_images"],
#     }

#     mongo_helper.read_collection(DATA).insert_one(doc)
#     print(f"Saved inspection {data['capture_id']} | Images: {len(data['captured_images'])}")


# lock = threading.Lock()

# while True:

#     capture_trigger = redis_helper.pull_data("capture_trigger")

#     if capture_trigger not in (True, "capture"):
#         time.sleep(0.05)
#         continue

#     redis_helper.push_data("capture_trigger", None)

#     current_capture_id = str(bson.ObjectId())
#     print("Capture triggered")

#     captured_images_dict = {}
#     threads = []

#     def capture_and_store(cam):
#         img = capture_image(cam)
#         if img is not None:
#             cam_id = cam.serial_number  
#             with lock:
#                 captured_images_dict[cam_id] = img

#     for cam in cameras:
#         t = threading.Thread(target=capture_and_store, args=(cam,))
#         t.start()
#         threads.append(t)

#     for t in threads:
#         t.join()

#     if not captured_images_dict:
#         print("No images captured")
#         continue

#     captured_at = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
#     # Get current date and hour
#     today = datetime.now().strftime("%Y_%m_%d")   # e.g., 2026_01_27
#     hour = datetime.now().strftime("%H")  
    
#     save_path = os.path.join(BUCKET_PATH, today, hour)
#     os.makedirs(save_path, exist_ok=True)

#     captured_image_urls = []
#     threads = []

#     def save_image(cam_id, img):
#         bson_id = str(bson.ObjectId())
#         file_path = os.path.join(save_path, f"{cam_id}_{bson_id}.jpg")
#         imwriter(file_path, img)

#         url = file_path.replace(BUCKET_PATH, "http://localhost:3307")
#         with lock:
#             captured_image_urls.append(url)

#     for cam_id, img in captured_images_dict.items():
#         t = threading.Thread(target=save_image, args=(cam_id, img))
#         t.start()
#         threads.append(t)

#     for t in threads:
#         t.join()

#     result_data = {
#         "capture_id": current_capture_id,
#         "captured_images": captured_image_urls,
#         "captured_at": captured_at
#     }

#     save_capture_data_util(result_data)
#     print(f"Capture complete | Images saved: {len(captured_image_urls)}")



# import basler_module
# import cv2
# from main_helper import *
# from datetime import datetime
# import bson
# import os
# import time
# import threading

# trigger_lock = threading.Lock()
# dict_lock = threading.Lock()


# def imwriter(path, image):
#     try:
#         cv2.imwrite(path, image)
#     except Exception as e:
#         print("Image write failed:", e)


# def capture_image(cam):
#     """
#     Safe software-trigger capture for Basler
#     """
#     try:
#         with trigger_lock:
#             cam.camera.ExecuteSoftwareTrigger()

#         # allow exposure time
#         time.sleep(0.02)

#         img = cam.get_image()
#         return img

#     except Exception as e:
#         print(f"Camera {cam.serial_number} capture error:", e)
#         return None



# redis_helper = RedisHelper()
# mongo_helper = MongoDBHelper()


# print("Waiting for camera initialization...")

# camera_ids = []
# cameras = []
# master = None
# initialized = False

# while not initialized:
#     config = redis_helper.pull_data("camera_config")

#     if not config:
#         time.sleep(0.1)
#         continue

#     if not isinstance(config, dict):
#         print("Invalid camera_config format")
#         time.sleep(0.1)
#         continue

#     camera_ids = config.get("camera_ids")

#     if not camera_ids or not isinstance(camera_ids, list):
#         print("Invalid camera_ids")
#         time.sleep(0.1)
#         continue

#     print("Initializing cameras:", camera_ids)

#     master = basler_module.basler_camera_master()
#     cameras = []

#     for cid in camera_ids:
#         try:
#             cam = basler_module.basler_camera_individual(
#                 master, cid, "SOFTWARE"
#             )

#             cameras.append(cam)
#             print(f"Camera {cid} ready")

#         except Exception as e:
#             print(f"Failed to init camera {cid}:", e)

#     if not cameras:
#         print("No cameras initialized")
#         time.sleep(0.5)
#         continue

#     initialized = True
#     redis_helper.push_data("camera_config", None)

#     print("Cameras initialized:", [c.serial_number for c in cameras])
#     time.sleep(0.5)  # warm-up

# print("Multi-camera capture service started")

# def save_capture_data(data):
#     mongo_helper.read_collection(DATA).insert_one({
#         "capture_id": data["capture_id"],
#         "captured_at": data["captured_at"],
#         "captured_images": data["captured_images"]
#     })
#     print(f"Saved capture {data['capture_id']}")


# while True:

#     trigger = redis_helper.pull_data("capture_trigger")

#     if trigger != "capture":
#         time.sleep(0.05)
#         continue

#     redis_helper.push_data("capture_trigger", None)

#     print("Capture triggered")

#     capture_id = str(bson.ObjectId())
#     captured_images = {}

#     def capture_worker(cam):
#         print(f"➡ Triggering camera {cam.serial_number}")
#         img = capture_image(cam)

#         if img is None:
#             print(f"No image from camera {cam.serial_number}")
#             return

#         print(f"Image received from camera {cam.serial_number}")
#         with dict_lock:
#             captured_images[cam.serial_number] = img

#     threads = []
#     for cam in cameras:
#         t = threading.Thread(target=capture_worker, args=(cam,))
#         t.start()
#         threads.append(t)

#     for t in threads:
#         t.join()

#     if not captured_images:
#         print("No images captured")
#         continue

#     today = datetime.now().strftime("%Y_%m_%d")
#     hour = datetime.now().strftime("%H")
#     save_dir = os.path.join(BUCKET_PATH, today, hour)
#     os.makedirs(save_dir, exist_ok=True)

#     image_urls = []

#     def save_worker(cam_id, img):
#         file_id = str(bson.ObjectId())
#         file_path = os.path.join(save_dir, f"{cam_id}_{file_id}.jpg")
#         imwriter(file_path, img)

#         url = file_path.replace(BUCKET_PATH, "http://localhost:3307")
#         with dict_lock:
#             image_urls.append(url)

#     threads = []
#     for cam_id, img in captured_images.items():
#         t = threading.Thread(target=save_worker, args=(cam_id, img))
#         t.start()
#         threads.append(t)

#     for t in threads:
#         t.join()

#     save_capture_data({
#         "capture_id": capture_id,
#         "captured_at": datetime.now().strftime("%Y_%m_%d_%H_%M_%S"),
#         "captured_images": image_urls
#     })

#     print(f"Capture complete | Images saved: {len(image_urls)}")




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

            # apply AOI if present
            # if aoi:
            #     cam.set_aoi(
            #         aoi["offset_x"],
            #         aoi["offset_y"],
            #         aoi["width"],
            #         aoi["height"]
            #     )

            # cam = basler_module.basler_camera_individual(
            #     master,
            #     serial,
            #     mode,
            #     aoi
            # )

            if aoi:
                # If AOI is provided, pass it to the constructor or set it after creation
                cam = basler_module.basler_camera_individual(
                    master,
                    serial,
                    mode,
                    aoi  # if constructor supports AOI
                )
            else:
                # No AOI, just initialize normally
                cam = basler_module.basler_camera_individual(
                    master,
                    serial,
                    mode
                )

            # If the SDK requires setting AOI after creation, do it like this:
            if aoi and not hasattr(cam, "aoi_in_constructor"):  # pseudo check
                cam.set_aoi(
                    aoi["offset_x"],
                    aoi["offset_y"],
                    aoi["width"],
                    aoi["height"]
                )


            cameras.append(cam)
            print(f"Camera {serial} ready | AOI: {aoi}")

        except Exception as e:
            print(f"Failed to init camera {cam_cfg}:", e)

    print("Active cameras:", [c.serial_number for c in cameras])
    save_running_cameras(camera_details,mode)
    time.sleep(0.5)



# def camera_config_watcher():
#     global last_camera_ids

#     print("Camera config watcher started")

#     while True:
#         config = redis_helper.pull_data("camera_config")

#         if not config or not isinstance(config, dict):
#             time.sleep(0.1)
#             continue

#         camera_ids = config.get("camera_ids")

#         if not camera_ids or not isinstance(camera_ids, list):
#             time.sleep(0.1)
#             continue

#         if camera_ids != last_camera_ids:
#             with camera_lock:
#                 initialize_cameras(camera_ids)
#                 last_camera_ids = camera_ids.copy()

#             redis_helper.push_data("camera_config", None)

#         time.sleep(0.1)


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

        if camera_ids != last_camera_ids:
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

