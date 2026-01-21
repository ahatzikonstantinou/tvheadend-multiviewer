You’ve built a genuinely impressive multiviewer system, Antonis — it deserves a README that explains the architecture clearly and helps future‑you (or anyone else) understand how everything fits together. Below is a clean, structured `README.md` you can drop directly into your repo. It reflects the actual behavior of your system: maxing videos, mobile fullscreen, mute logic, volume control, layout, and the TVH streaming backend.

---

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

## 🚀 Getting Started

### **1. Install TVHeadend**
Ensure TVH is running and accessible, with each channel available via:

```
http://<tvh-host>:9981/stream/channel/<channel-id>?profile=webtv-mp4
```

### **2. Configure channels**
Edit `channels.json`:

```json
[
  {
    "name": "Channel 1",
    "url": "http://tvh:9981/stream/channel/1?profile=webtv-mp4",
    "logo": "assets/ch1.png"
  }
]
```

### **3. Serve the project**
Any static server works:

```
python3 -m http.server
```

Then open:

```
http://<your-device>:8000
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

---

If you want, I can also generate a **shorter README**, a **more technical one**, or a **GitHub‑optimized version with badges and screenshots**.