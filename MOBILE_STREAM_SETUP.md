# 📱 Mobile Live Camera Streaming — Setup Guide

> **IITB Integrated Security System · Smartphone Camera Module**

This feature lets a security guard point their phone at a scene and have the
live video fed directly into the existing face-recognition and object-detection
pipeline — no extra app required, just a browser link.

---

## What this adds

| Component | What it does |
|-----------|-------------|
| **MediaMTX** (Docker) | WebRTC/WHIP relay that receives the phone's video and re-publishes it as RTSP |
| **`mobile_stream.py`** | FastAPI router that registers the phone stream and starts AI detection |
| **Mobile HTML page** | Self-contained browser UI served at `/api/v1/mobile/stream/page` |

**Flow:**
```
Phone Browser  ──WHIP/WebRTC──►  MediaMTX (:8889)
MediaMTX       ──RTSP──────────►  Backend VideoProcessor
                                   (face recognition + object detection)
```

---

## Prerequisites

- Docker Desktop running  
- The rest of the stack already working (`docker-compose up db backend`)

---

## Step 1 — Start MediaMTX

```bash
# From the project root
docker-compose up mediamtx -d
```

Verify it is running:

```bash
docker-compose ps mediamtx
# Should show "Up" and ports 8554, 8889
```

---

## Step 2 — Get a JWT token

### Option A — Dashboard (easiest)
1. Log in at `http://localhost:5000`
2. Open **DevTools → Network**
3. Look for any API request and copy the `Authorization: Bearer <token>` value

### Option B — curl
```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@security.iitb.ac.in","password":"admin123"}' \
  | python -m json.tool
```
Copy the `access_token` value from the response.

---

## Step 3 — Find your laptop's local IP

```cmd
ipconfig
```

Look for the **IPv4 Address** under your active network adapter (e.g., `192.168.1.42`).

---

## Step 4 — Open on the phone

> [!IMPORTANT]
> Your phone must be on **the same Wi-Fi network** as your laptop.

Send this URL to the guard's phone (WhatsApp / QR code / any messenger):

```
http://YOUR_LAPTOP_IP:8000/api/v1/mobile/stream/page?stream_id=phone_guard1&token=YOUR_JWT_TOKEN
```

**Example:**
```
http://192.168.1.42:8000/api/v1/mobile/stream/page?stream_id=phone_guard1&token=eyJhbGci...
```

The guard taps **▶ Start Streaming** — that's it. The video appears in the
security dashboard alongside the regular RTSP cameras.

---

## Customising the stream ID

Use any unique identifier per device:

| Guard | `stream_id` |
|-------|-------------|
| Main Gate | `phone_maingate` |
| Guard 1   | `phone_guard1`   |
| Patrol A  | `phone_patrol_a` |

The RTSP URL will be `rtsp://localhost:8554/<stream_id>` and will show up in
active streams in the dashboard.

---

## Detection modes

Add `&detection_mode=face` (or `object` or `both`) to the URL:

```
http://192.168.1.42:8000/api/v1/mobile/stream/page?stream_id=phone_guard1&token=TOKEN&detection_mode=face
```

| Mode | What runs |
|------|-----------|
| `face` | Face recognition only |
| `object` | RF-DETR object detection only |
| `both` | Both pipelines (default) |

---

## Remote access (outside local network)

Install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/):

```bash
# One-liner — exposes the backend publicly via HTTPS tunnel
cloudflared tunnel --url http://localhost:8000
```

Cloudflare prints a random HTTPS URL like `https://xyz.trycloudflare.com`.
Use that as the base URL for the phone link — HTTPS is required for camera
access on real phones outside localhost.

> [!NOTE]
> MediaMTX WHIP also needs to be reachable. Either:
> - Run a second tunnel: `cloudflared tunnel --url http://localhost:8889`
> - Or set up a reverse proxy (nginx) to forward `/whip/` to port 8889.
> - Or use a VPN (Tailscale / ZeroTier) so the phone can reach your laptop's LAN IP directly.

---

## API reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/mobile/stream/register` | JWT | Register phone stream, start detection |
| `GET`  | `/api/v1/mobile/stream/{id}/status` | — | Stream status & stats |
| `POST` | `/api/v1/mobile/stream/{id}/stop` | — | Stop stream |
| `GET`  | `/api/v1/mobile/stream/page` | token param | Mobile HTML page |

---

## Troubleshooting

### "Camera access requires HTTPS"
- Use `localhost` on the same machine, **or**
- Use a Cloudflare tunnel for HTTPS, **or**
- Configure your router/nginx to serve HTTPS with a self-signed cert.

### "MediaMTX WHIP error: 404"
- Check MediaMTX is running: `docker-compose ps mediamtx`
- Check port 8889 is not blocked by Windows Firewall.

### Video starts but detection doesn't trigger
- Check backend logs: `docker-compose logs backend -f`
- Ensure the VideoProcessor is not already at its stream limit.

### "Registration failed (401)"
- Token has expired. Get a fresh token (Step 2) and regenerate the link.

### Phone can't reach the server
- Confirm phone and laptop are on the same Wi-Fi.
- Try pinging your laptop IP from the phone browser.
- Check Windows Firewall: allow inbound on ports **8000** and **8889**.

```powershell
# Allow ports through Windows Firewall (run as Administrator)
netsh advfirewall firewall add rule name="IITB Backend" protocol=TCP dir=in localport=8000 action=allow
netsh advfirewall firewall add rule name="IITB MediaMTX WebRTC" protocol=TCP dir=in localport=8889 action=allow
netsh advfirewall firewall add rule name="IITB MediaMTX WebRTC UDP" protocol=UDP dir=in localport=8889 action=allow
netsh advfirewall firewall add rule name="IITB MediaMTX RTSP" protocol=TCP dir=in localport=8554 action=allow
```
