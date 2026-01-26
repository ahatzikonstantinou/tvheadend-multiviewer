# TV Mosaic Multiviewer

A lightweight, browser‑based multiviewer for live TV streams.  
Designed for Raspberry Pi 4 deployments and optimized for low‑latency H.264/H.265 playback using TVHeadend (`tvh`) as the backend.

The interface displays multiple live channels in a responsive grid, allows maxing any channel with a double‑tap/double‑click, and provides unified mute/volume control. On smartphones, maxing a video automatically enters fullscreen mode for an immersive viewing experience.

---

## ✨ Features

### **Responsive multichannel grid**
- Displays any number of channels in a flexible CSS grid.
- Automatically wraps cells based on viewport size.

### **Max‑view mode**
- Double‑tap/double‑click any video to expand it.
- Other channels move to a small-row strip below.
- Double‑tap again to return to grid mode.

### **Mobile fullscreen integration**
- On smartphones, maxing a video automatically enters browser fullscreen.
- Unmaxing exits fullscreen.
- Ensures the infobar (mute/refresh) remains visible.

### **Unified audio control**
- Only one video can be unmuted at a time.
- Global volume slider applies to all videos.
- Volume persists via `localStorage`.

### **TVHeadend integration**
- Streams are loaded using `profile=webtv-mp4` for broad compatibility.
- Channel list and URLs are defined in a JSON configuration.

### **Double‑tap gesture support**
- Custom double‑tap detector ensures consistent behavior on mobile.
- Avoids browser zoom and gesture conflicts.

### Important!
Browsers have a limit of 6 concurrent open http connections. Therefore TV-Mosaic can only display 6 concurrent channels. You can have more in the grid, but in order to activate them try hitting refresh until it hijacks the connection of another that is already active.
If you wish to see more than 6 channels, configure another grid with different chanells and open it in a different browser (or maybe incognito window of the same browser).

---

## 📁 Project Structure

| **File/Folder** | **Description** |
| --- | --- |
| **index.html** | Main UI layout, header, grid, max-container, small-row. |
| **style.css** | Responsive grid, max-mode layout, infobar styling. |
| **app.js** | Core logic: video creation, max/unmax, mute logic, volume control, mobile fullscreen. |
| **channels.json** | Channel definitions (name, TVH URL, icons). |
| **assets/** | Channel logos, icons, optional images. |

---

# 📦 Installation

This project is a lightweight, static web application.  
You can run it on any machine that can serve HTML/CSS/JS files — including a Raspberry Pi 4.

Below are the recommended installation steps using a Python virtual environment.

---

## 1. Clone the repository

```bash
git clone https://github.com/<your-repo>/tv-mosaic-multiviewer.git
cd tv-mosaic-multiviewer
```

---

## 2. Create and activate a virtual environment

Although the project itself is static, using a venv keeps your tools isolated and clean.

```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows:

```powershell
python -m venv venv
venv\Scripts\activate
```

---

## 3. Install required Python libraries

The multiviewer itself does **not** require Python libraries, but you may want:

- A simple static server (`http.server`)
- Optional helpers (e.g., generating channel lists, validating JSON)

Recommended minimal dependencies:

```bash
pip install flask requests
```

If you want to serve the project using Flask instead of a raw static server:

```bash
pip install flask waitress
```

If you want to validate your `channels.json`:

```bash
pip install jsonschema
```

---

## 4. Start a development server

### Simple Python static server (recommended)

```bash
python3 -m app.py 7070
```

Then open:

```
http://<your-device-ip>:7070
```

Run it:

```bash
python serve.py
```

---

## 5. Configure

In a browser navigate to `http://192.168.3.104:7070/`

Configure:
- TVHeadend Url
- Grid
- Channel mappiings to the grid's cells

Make sure:

- TVH is reachable from the device running the browser
- You use `profile=webtv-mp4` for maximum compatibility

---

## 6. Open the multiviewer

Navigate to:

```
http://<your-device-ip>:7070
```

You should now see:

- The responsive grid
- Live video streams
- Double‑tap maxing
- Mobile fullscreen behavior
- Global volume control

---


# 📡 Deployment on Raspberry Pi 4

The multiviewer runs extremely well on a Raspberry Pi 4 thanks to its hardware‑accelerated H.264/H.265 decoding and low power consumption.  
This section walks you through preparing the Pi, setting up the project, and enabling automatic startup using `systemd`.

---

## 1. Update and install dependencies

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3 python3-venv git
```

---

## 2. Clone the project

```bash
cd /home/pi
git clone https://github.com/<your-repo>/tv-mosaic-multiviewer.git
cd tv-mosaic-multiviewer
```

---

## 3. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

---

## 4. Install optional Python tools (if needed)

```bash
pip install flask waitress jsonschema
```

These are optional — the multiviewer itself is static and works with `http.server`.

---

## 5. Test the server manually

```bash
source venv/bin/activate
python3 -m app.py 7070
```

Open in your browser:

```
http://<raspberry-pi-ip>:7070
```

If everything loads correctly, continue to the next step.

---

# 🔧 systemd Service (Autostart on Boot)

Create a systemd service file so the multiviewer starts automatically when the Pi boots.

---

## 1. Create the service file

```bash
sudo nano /etc/systemd/system/multiviewer.service
```

Paste this:

```ini
[Unit]
Description=TV Mosaic Multiviewer
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/tv-mosaic-multiviewer
ExecStart=/home/pi/tv-mosaic-multiviewer/venv/bin/python3 -m http.server 7070
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Notes
- `User=pi` ensures the server runs as the normal user.
- `Restart=always` keeps it alive if it crashes.
- `WorkingDirectory` must match your actual project path.

---

## 2. Reload systemd

```bash
sudo systemctl daemon-reload
```

---

## 3. Enable the service on boot

```bash
sudo systemctl enable multiviewer.service
```

---

## 4. Start it now

```bash
sudo systemctl start multiviewer.service
```

---

## 5. Check status

```bash
sudo systemctl status multiviewer.service
```

You should see:

- Active: **active (running)**
- ExecStart: python3 -m http.server 7070

Your multiviewer is now permanently running at:

```
http://<raspberry-pi-ip>:7070
```

Even after reboots.


---


## Systemd service

### Install the service

#### **Step 1 — Enable (i.e. autostart) the service using the full path e.g. for /opt/tv-mosaic**
```
sudo systemctl enable /opt/tv-mosaic/tv-mosaic.service
```

#### **Step 2 — Check status**
```
sudo systemctl status tv-mosaic.service
```

#### **Step 3 — View logs**
```
journalctl -u mosaic.service -f
```

### Manage the service

#### **To manually start the service**
```
sudo systemctl start tv-mosaic.service
```

#### **To manually stop the service**
```
sudo systemctl stop tv-mosaic.service
```

#### **To uninstall the service**
```
sudo systemctl didsable tv-mosaic.service
```

---

## Prerequisite

### **Install TVHeadend**
Ensure TVH is running and accessible, with each channel available via:

```
http://<tvh-host>:9981/stream/channel/<channel-id>?profile=webtv-mp4
```

---

## 📱 Mobile Behavior

### **Automatic fullscreen**
- When a video is maxed, the browser enters fullscreen.
- When unmaxed, fullscreen exits.
- Ensures the video + infobar fill the entire screen.

### **Internal scrolling**
- The small-row remains accessible without breaking fullscreen.
- Double‑tap gestures remain reliable.

---

## 🔊 Audio Logic

### **Mute/unmute**
- Only one video can be unmuted at a time.
- Switching maxed videos transfers audio if the previous one was unmuted.

### **Global volume**
- Slider controls volume of all videos.
- Value saved in `localStorage`.

---

## 🧩 Key Functions

### **createCell()**
Builds each video cell, infobar, and event listeners.

### **enableMaxMode()**
Moves the selected cell into the maxed slot and rearranges others.

### **disableMaxMode()**
Restores the grid layout.

### **handleMuteToggle()**
Ensures only one video plays audio.

### **setupGlobalVolumeControl()**
Applies volume to all videos and persists it.

### **addDoubleTapListener()**
Unified double‑tap/double‑click handler for mobile and desktop.

---

## 🛠 Requirements

- TVHeadend server
- Modern browser (Chrome, Firefox, Safari)
- Optional: Raspberry Pi 4 for deployment

---

## 📄 License

MIT License — free to use, modify, and distribute.