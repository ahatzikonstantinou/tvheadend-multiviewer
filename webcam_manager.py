import os
import subprocess
import atexit
import json
from urllib.parse import urlparse

class Go2RtcManager:
    def __init__(self, binary_name="go2rtc", url="http://localhost:1984",webrtc_port=":8555"):
        # Βρίσκει τον απόλυτο κατάλογο στον οποίο βρίσκεται το παρόν αρχείο
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        self.go2rtc_url = url
        
        # Ενώνει τον κατάλογο του backend με το όνομα του αρχείου go2rtc
        self.binary_path = os.path.join(backend_dir, binary_name)
        self.webrtc_port = webrtc_port
        self.process = None
        self.current_cameras = {}
        
        # Εξασφάλιση τερματισμού κατά την έξοδο της Flask
        atexit.register(self.stop)

    def start(self, cameras_dict, go2rtc_url="http://localhost:1984"):
        """Ξεκινάει το go2rtc με τις κάμερες που του δίνονται"""
        self.current_cameras = cameras_dict
        self.go2rtc_url = go2rtc_url.rstrip('/')
        print(f"[go2rtc] Το URL ορίστηκε σε: {self.go2rtc_url}")

        # Αυτόματη εξαγωγή της API πόρτας από το go2rtc_url (π.χ. 1984)
        try:
            parsed_url = urlparse(go2rtc_url)
            api_port = f":{parsed_url.port}" if parsed_url.port else ":1984"
        except Exception:
            api_port = ":1984"

        # Δημιουργία της δομής ρυθμίσεων σε μορφή λεξικού (Dict)
        config_structure = {
            "streams": cameras_dict,
            "api": {
                "listen": api_port,
                "origin": "*"
            },
            "webrtc": {
                "listen": self.webrtc_port
            }
        }

        # Μετατροπή του Dict σε ένα compact JSON string
        inline_config = json.dumps(config_structure)
        print(f"[go2rtc] Εκκίνηση του go2rtc με inline config: {inline_config}")
        try:
            self.process = subprocess.Popen(
                [self.binary_path, "-config", inline_config],                
                stderr=None,     # makes go2rtc print errors to the console
                stdout=subprocess.DEVNULL
                # stderr=subprocess.DEVNULL
            )
            print(f"[go2rtc] Ξεκίνησε επιτυχώς με {len(cameras_dict)} κάμερες.")
            print(f"[go2rtc] API Port: {api_port} | WebRTC Port: {self.webrtc_port}")
        except Exception as e:
            print(f"[go2rtc] ΚΡΙΣΙΜΟ ΣΦΑΛΜΑ κατά την εκκίνηση του binary: {e}")

    def stop(self):
        """Τερματίζει με ασφάλεια και ακαριαία το subprocess"""
        if self.process:
            print("[go2rtc] Τερματισμός της διεργασίας...")
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                print("[go2rtc] Δεν ανταποκρίνεται. Kill process...")
                self.process.kill()
                self.process.wait()
            self.process = None
            print("[go2rtc] Η διεργασία τερματίστηκε επιτυχώς.")

    def update_streams(self, new_go2rtc_url, new_cameras_dict):
        """Ελέγχει αν άλλαξε το URL του go2rtc μετά από αλλαγή των settings"""
        if new_go2rtc_url and self.go2rtc_url != new_go2rtc_url.rstrip('/'):
            old_url = self.go2rtc_url
            self.go2rtc_url = new_go2rtc_url.rstrip('/')
            print(f"[go2rtc] Το URL άλλαξε από {old_url} σε {self.go2rtc_url}")
        else:
            print("[go2rtc] Δεν ανιχνεύθηκε αλλαγή στο go2rtc URL.")
            
        """Ελέγχει για αλλαγές και κάνει restart το go2rtc αν χρειαστεί"""
        if self.current_cameras != new_cameras_dict:
            print("[go2rtc] Ανιχνεύθηκε αλλαγή στα URLs των καμερών. Γίνεται επανεκκίνηση...")
            self.stop()
            self.start(new_cameras_dict)
        else:
            print("[go2rtc] Δεν βρέθηκαν αλλαγές στα URLs. Δεν απαιτείται επανεκκίνηση.")