from pypylon import pylon
import cv2
import time
import datetime
from main_helper import RedisHelper
from constants import *
import logging
import sys
import threading
redis_helper = RedisHelper()

logging.basicConfig(
	level=logging.DEBUG,
	format="%(asctime)s - %(levelname)s - %(message)s",
	filename="base.log",  # Save logs to a file
	filemode="a"  # Overwrite file on each run
)

HARDWARE = 'HARDWARE'
SOFTWARE = 'SOFTWARE'


redis_helper.push_data(CAMERA_HEALTH,True)
redis_helper.push_data(CAMERA_MESSAGE,f" ")

class basler_camera_master():
	def __init__(self) -> None:
		# camera = None
		self.tl_factory = pylon.TlFactory.GetInstance()
		self.devices = self.tl_factory.EnumerateDevices()
		print('Number of devices found',self.devices)

class basler_camera_individual():
	def __init__(self,master,desired_serial_number,mode=SOFTWARE,aoi_config = None):
		# Find the camera with the desired serial number
		self.serial_number = desired_serial_number
		self.camera = None
		camera = None
		for device in master.devices:
			print(device.GetSerialNumber())
			if device.GetSerialNumber() == desired_serial_number:
				print(f'found {desired_serial_number}')
				camera = pylon.InstantCamera(master.tl_factory.CreateDevice(device))
				print(f'created,{desired_serial_number}')
				break
		if camera is None:
			print(f"Camera with serial number {desired_serial_number} not found.")
			redis_helper.push_data(f'{CAMERA_HEALTH}_{self.serial_number}',False)
			redis_helper.push_data(f'{CAMERA_MESSAGE}_{self.serial_number}',f"Camera with serial number {desired_serial_number} not found.")

			return
		print(f"Camera {desired_serial_number} available.")
		camera.Open()
		print(f"Camera {desired_serial_number} opened successfully.")
		redis_helper.push_data(f'{CAMERA_HEALTH}_{self.serial_number}',True)
		redis_helper.push_data(f'{CAMERA_MESSAGE}_{self.serial_number}',f" ")
		# camera.AcquisitionMode.SetValue('Continuous')

		if aoi_config is not None:
			camera.OffsetX.SetValue(0)
			camera.OffsetY.SetValue(0)
			camera.Width.SetValue(aoi_config['Width'])
			camera.Height.SetValue(aoi_config['Height'])
			camera.OffsetX.SetValue(aoi_config['OffsetX'])
			camera.OffsetY.SetValue(aoi_config['OffsetY'])

		self.image = None
		self.timeout = 0.06
		self.serial_number = desired_serial_number
		self.master = master
		self.camera = camera
		self.default_mode = mode
		self.current_acquisition_mode = None
		self.acquisition_mode(mode)

	def reinitialise(self):
		camera = None
		for device in self.master.devices:
			print(device.GetSerialNumber())
			if device.GetSerialNumber() == self.serial_number:
				camera = pylon.InstantCamera(self.master.tl_factory.CreateDevice(device))
				break
		if camera is None:
			redis_helper.push_data(f'{CAMERA_HEALTH}_{self.serial_number}',False)
			redis_helper.push_data(f'{CAMERA_MESSAGE}_{self.serial_number}',f" {self.serial_number} Camera error !!!.")


			print(f"Camera error !!!.")
			return
		camera.Open()
		print(f"Camera {self.serial_number} opened successfully.")
		redis_helper.push_data(f'{CAMERA_HEALTH}_{self.serial_number}',True)
		redis_helper.push_data(f'{CAMERA_MESSAGE}_{self.serial_number}',f" ")

		self.camera = camera
		self.current_acquisition_mode = None
		self.acquisition_mode(self.default_mode)

	def acquisition_mode(self,mode):
		if self.current_acquisition_mode != mode:
			if mode == HARDWARE:
				start = time.time()
				self.camera.StopGrabbing()
				self.camera.TriggerMode.SetValue('On')  # Enable trigger mode
				self.camera.TriggerSource.SetValue('Line1')
				# self.camera.TriggerActivation.SetValue('RisingEdge')  # Trigger on rising edge of the signal
				self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
				# self.camera.StartGrabbing(pylon.GrabStrategy_OneByOne)
				print('modification to hardware',time.time()-start)
				self.current_acquisition_mode = mode
			else:
				start = time.time()
				self.camera.StopGrabbing()
				self.camera.TriggerMode.SetValue('On')  # Enable trigger mode
				self.camera.TriggerSource.SetValue('Software')  # Use Line1 as the trigger source (depends on your setup)
				# self.camera.TriggerActivation.SetValue('RisingEdge')  # Trigger on rising edge of the signal
				self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
				# self.camera.StartGrabbing(pylon.GrabStrategy_OneByOne)
				logging.info(f'modification to software {time.time()-start}')
				self.current_acquisition_mode = mode
				logging.info(f"{self.serial_number},{self.camera.TriggerMode.GetValue()},{self.camera.TriggerSource.GetValue()}")
	
	def get_image(self,cam_number = None):
		try:
			try:
				self.camera.WaitForFrameTriggerReady(2000)  # Increase timeout to 10 seconds (10000 ms)
			except Exception as e:
				print(f'Timeout waiting for trigger signal.{self.serial_number} {e}')
				if 'LogicalErrorException' in str(e):
					redis_helper.push_data(f'{CAMERA_HEALTH}_{self.serial_number}',False)
					redis_helper.push_data(f'{CAMERA_MESSAGE}_{self.serial_number}',f"Not able to get the image , {self.serial_number} {cam_number}")
					time.sleep(0.1)
					try:
						self.reinitialise()
					except Exception as e:
						# print(datetime.datetime.now(),f'Camera Reinitialisation error for serial number {self.serial_number}',e)
						print(f'Camera Reinitialisation trigger error for serial number {self.serial_number} {cam_number} {e}')
						# return None
						self.image = None
				# print("Timeout waiting for trigger signal.")
				
				return None
			# Trigger the camera manually via hardware signal (this is where the external trigger happens)
			self.camera.ExecuteSoftwareTrigger()  # Simulate the hardware trigger to capture an image

			# Retrieve the captured image
			try:
				grab_result = self.camera.RetrieveResult(10, pylon.TimeoutHandling_ThrowException)
				# with self.camera.RetrieveResult(20, pylon.TimeoutHandling_ThrowException) as temp:
				#     grab_result = temp
			except Exception as e:
				grab_result = None
				# print('Camera Module error',e)
				print(f'Camera Module error {self.serial_number} {e}')
				return None

			if grab_result:
				if grab_result.GrabSucceeded():
					# Convert the raw image into a format suitable for YOLO input (OpenCV)
					img = grab_result.GetArray()

					# Convert image from RGB to BGR (OpenCV uses BGR format)
					img_bgr = cv2.cvtColor(img, cv2.COLOR_BAYER_RG2RGB)

					# Perform object detection using YOLOv8 with custom confidence and IoU thresholds
					# Resize the image to the desired input size (1280x1280) before passing to the model
					# resized_img = cv2.resize(img_bgr, (input_image_size, input_image_size))

					# # Perform inference on the resized image
					# results = model(resized_img, conf=confidence_threshold, iou=iou_threshold, imgsz=input_image_size)  # Set both thresholds

					# # Use plot() to overlay detections onto the image
					# img_with_boxes = results[0].plot()  # Use the first result (YOLO inference on one image)
					redis_helper.push_data(f'{CAMERA_HEALTH}_{self.serial_number}',True)
					return img_bgr
		except Exception as e:
			print(f'camera error {self.serial_number} {e}')
			redis_helper.push_data(f'{CAMERA_HEALTH}_{self.serial_number}',False)
			redis_helper.push_data(f'{CAMERA_MESSAGE}_{self.serial_number}',f"Not able to get the image , {self.serial_number} {cam_number}")
			

			try:
				self.reinitialise()
			except Exception as e:
				# print(datetime.datetime.now(),f'Camera Reinitialisation error for serial number {self.serial_number}',e)
				print(f'Camera Reinitialisation error for serial number {self.serial_number} {e}')
				return None
			
	def get_image_thread(self,cam_number):
		start_timeout = time.time()
		try:
			try:
				self.camera.WaitForFrameTriggerReady(10)  # Increase timeout to 10 seconds (10000 ms)
			except Exception as e:
				# print("Timeout waiting for trigger signal.")
				print(f'Timeout waiting for trigger signal.{self.serial_number} {cam_number} {e}')
				# return None
				self.image = None
			# Trigger the camera manually via hardware signal (this is where the external trigger happens)
			self.camera.ExecuteSoftwareTrigger()  # Simulate the hardware trigger to capture an image

			# Retrieve the captured image
			try:
				grab_result = self.camera.RetrieveResult(20, pylon.TimeoutHandling_ThrowException)
				# with self.camera.RetrieveResult(20, pylon.TimeoutHandling_ThrowException) as temp:
				#     grab_result = temp
			except Exception as e:
				grab_result = None
				# print('Camera Module error',e)
				print(f'Camera Module error {self.serial_number} {cam_number} {e}')
				# return None
				self.image = None

			if grab_result:
				if grab_result.GrabSucceeded():
					# Convert the raw image into a format suitable for YOLO input (OpenCV)
					img = grab_result.GetArray()

					# Convert image from RGB to BGR (OpenCV uses BGR format)
					img_bgr = cv2.cvtColor(img, cv2.COLOR_BAYER_RG2RGB)

					# Perform object detection using YOLOv8 with custom confidence and IoU thresholds
					# Resize the image to the desired input size (1280x1280) before passing to the model
					# resized_img = cv2.resize(img_bgr, (input_image_size, input_image_size))

					# # Perform inference on the resized image
					# results = model(resized_img, conf=confidence_threshold, iou=iou_threshold, imgsz=input_image_size)  # Set both thresholds

					# # Use plot() to overlay detections onto the image
					# img_with_boxes = results[0].plot()  # Use the first result (YOLO inference on one image)
					# return img_bgr
					if time.time() - start_timeout < self.timeout:
						self.image = img_bgr
						print(f'Camera image acquired {self.serial_number} {cam_number} {time.time() - start_timeout}')
						redis_helper.push_data(f'{CAMERA_HEALTH}_{self.serial_number}',True)
					else:
						print(f'Camera {self.serial_number} {cam_number} Timeout {time.time() - start_timeout}')
		except Exception as e:
			print(f'camera error {self.serial_number} {e}')
			redis_helper.push_data(f'{CAMERA_HEALTH}_{self.serial_number}',False)
			redis_helper.push_data(f'{CAMERA_MESSAGE}_{self.serial_number}',f"Not able to get the image , {self.serial_number} {cam_number}")
			

			try:
				self.reinitialise()
			except Exception as e:
				# print(datetime.datetime.now(),f'Camera Reinitialisation error for serial number {self.serial_number}',e)
				print(f'Camera Reinitialisation ṇerror for serial number {self.serial_number} {cam_number} {e}')
				# return None
				self.image = None
			
	def get_image_new(self,cam_number=None):
		t = threading.Thread(target=self.get_image_thread,args=(cam_number,))
		t.start()
		start_timeout = time.time()
		while 1:
			if self.image is not None:
				# Clear it to avoid reusing
				return self.image
				# return img
			if time.time() - start_timeout >= self.timeout:
				print(f'Camera {self.serial_number} {cam_number} Thread timeout {time.time() - start_timeout}')
				return None

		
	def get_image_with_mode(self,mode=HARDWARE,timeout=15):
		start = time.time()
		self.acquisition_mode(mode)
		if mode == HARDWARE:
			while 1:
				img = self.get_image()
				if img is not None:
					
					return img
				if time.time() - start >= timeout:
					return None
		else:
			self.camera.ExecuteSoftwareTrigger()
			while 1:
				img = self.get_image()
				if img is not None:
					self.acquisition_mode(HARDWARE)
					return img
				if time.time() - start >= timeout:
					return None
	
	def close(self):
		self.camera.StopGrabbing()
		self.camera.Close()


class basler_camera_continous():
	def __init__(self,master,desired_serial_number,aoi_config = None):
		# Find the camera with the desired serial number
		camera = None
		for device in master.devices:
			print(device.GetSerialNumber())
			if device.GetSerialNumber() == desired_serial_number:
				camera = pylon.InstantCamera(master.tl_factory.CreateDevice(device))
				break
		if camera is None:
			print(f"Camera with serial number {desired_serial_number} not found.")
			return None
		camera.Open()
		print(f"Camera {desired_serial_number} opened successfully.")
		# # print(dir(camera))
		print('Previous Buffer',camera.MaxNumBuffer.GetValue())

		print('Current Buffer',camera.MaxNumBuffer.SetValue(1),camera.MaxNumBuffer.GetValue())
		# # sys.exit(0)
		# camera.TriggerMode.SetValue('On')  # Enable trigger mode
		
		# camera.TriggerSource.SetValue('Line1')  # Use Line1 as the trigger source (depends on your setup)
		# camera.TriggerActivation.SetValue('RisingEdge')  # Trigger on rising edge of the signal
		if aoi_config is not None:
			camera.Width.SetValue(aoi_config['Width'])
			camera.Height.SetValue(aoi_config['Height'])
			camera.OffsetX.SetValue(aoi_config['OffsetX'])
			camera.OffsetY.SetValue(aoi_config['OffsetY'])
		camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
		# camera.StartGrabbing(pylon.GrabStrategy_OneByOne)

		self.camera = camera

	

	def get_image(self):
		try:
			grab_result = self.camera.RetrieveResult(40, pylon.TimeoutHandling_ThrowException)

			if not grab_result.GrabSucceeded():
				print("Failed to grab image.")
				return None

			img = grab_result.GetArray()

			if img is not None:
				img = cv2.cvtColor(img, cv2.COLOR_BAYER_RG2BGR)

			return img

		except Exception as e:
			print(f"Error retrieving image: {e}")
			return None

		finally:
			if 'grab_result' in locals() and grab_result.IsValid():
				grab_result.Release()


	def close(self):
		self.camera.StopGrabbing()
		self.camera.Close()





class basler_camera_connector:
    """
    Class to enumerate all connected Basler cameras and push their info to Redis.
    Can also return the list of connected cameras.
    """
    def __init__(self):
        self.redis_key = "cameras"
        self.tl_factory = pylon.TlFactory.GetInstance()
        self.devices = []          # Low-level device objects
        self.cameras_info = []     # High-level camera info
        self.enumerate_cameras()

    def enumerate_cameras(self):
        """
        Enumerate all connected cameras, store info, and push to Redis.
        """
        devices = self.tl_factory.EnumerateDevices()
        self.devices = devices

        # Clear previous Redis entry
        # redis_helper.push_data(self.redis_key, None)

        if not devices:
            print("No cameras found.")
            self.cameras_info = []
            return []

        camera_list = []

        for device in devices:
            camera = pylon.InstantCamera(self.tl_factory.CreateDevice(device))
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

        self.cameras_info = camera_list
        redis_helper.push_data(self.redis_key, camera_list)
        print(f"Found {len(camera_list)} cameras.")
        return camera_list

    def get_camera_by_serial(self, serial_number):
        """
        Returns the device object for a given serial number, or None if not found.
        """
        for device in self.devices:
            if device.GetSerialNumber() == serial_number:
                return device
        return None
