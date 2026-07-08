class Session:
    def __init__(self):
        pass

class SessionRunner:
    def __init__(self, session: Session, screen_manager):
        self.screen_manager = screen_manager

    def run(self):
        screenshot_info = self.screen_manager.capture_screen()
        image_base64 = screenshot_info["image_base64"]
        path = screenshot_info["path"]
        scale = screenshot_info["scale"]
        phash = screenshot_info["phash"]
        return {
            "image_base64": image_base64,
            "path": path,
            "scale": scale,
            "phash": phash
        }
        