
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
