# from pypylon import pylon
# from main_helper import *
# import json

# redis_helper = RedisHelper()


# # Get the Transport Layer Factory
# tlf = pylon.TlFactory.GetInstance()

# # Get all available cameras
# devices = tlf.EnumerateDevices()

# if len(devices) == 0:
#     print("No cameras found.")
# else:
#     camera_list = []

#     for device in devices:
#         camera_info = {
#             "device_class": device.GetDeviceClass(),
#             "model_name": device.GetModelName(),
#             "serial_number": device.GetSerialNumber(),
#             "friendly_name": device.GetFriendlyName(),
#         }
#         camera_list.append(camera_info)

#     redis_helper.push_data("cameras", camera_list)

    # redis_helper.push_data("cameras",json.dump(devices))

    # print(f"Found {len(devices)} cameras:")
    # # Print information for each device
    # for i, device in enumerate(devices):
    #     print(f"--- Camera {i+1} ---")
    #     print(f"Device Class: {device.GetDeviceClass()}")
    #     print(f"Model Name: {device.GetModelName()}")
    #     print(f"Serial Number: {device.GetSerialNumber()}")
    #     print(f"Friendly Name: {device.GetFriendlyName()}")




from pypylon import pylon
from main_helper import *
import json

redis_helper = RedisHelper()

# Get the Transport Layer Factory
tlf = pylon.TlFactory.GetInstance()

# Enumerate connected cameras
devices = tlf.EnumerateDevices()

redis_helper.push_data("cameras", None)


if not devices:
    print("No cameras found.")
else:
    camera_list = []

    for device in devices:
        camera = pylon.InstantCamera(tlf.CreateDevice(device))
        camera.Open()

        camera_info = {
            "device_class": device.GetDeviceClass(),
            "model_name": device.GetModelName(),
            "serial_number": device.GetSerialNumber(),
            "friendly_name": device.GetFriendlyName(),
            "width": camera.Width.GetValue(),
            "height": camera.Height.GetValue(),
            "offset_x": camera.OffsetX.GetValue(),
            "offset_y": camera.OffsetY.GetValue()
        }

        camera_list.append(camera_info)
        camera.Close()

    redis_helper.push_data("cameras", camera_list)
