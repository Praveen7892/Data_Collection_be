# camera_service.py
import basler_module
import threading

class CameraService:
    def __init__(self):
        self.master = None
        self.cameras = []
        self.lock = threading.Lock()
        self.initialized = False

    def initialize(self, camera_ids):
        with self.lock:
            if self.initialized:
                return

            self.master = basler_module.basler_camera_master()
            self.cameras = [
                basler_module.basler_camera_individual(
                    self.master, cid, "SOFTWARE"
                )
                for cid in camera_ids
            ]

            self.initialized = True
            print(f"Cameras initialized: {camera_ids}")

    def get_cameras(self):
        return self.cameras
