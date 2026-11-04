# SecureHome: Face Recognition Home Security

A web-based home security system that watches a webcam, recognises the people you have approved, and emails you a photo when an unknown visitor stays in front of the camera. Face recognition runs on your own computer, with no cloud service.

Built with **Flask, MySQL, OpenCV, DeepFace (ArcFace) and scikit-learn**.

<!-- Add screenshots here, for example:
![Dashboard](docs/screenshots/dashboard.png)
![Live camera](docs/screenshots/camera.png)
-->

## Features

- **Live camera** with viewfinder-style boxes. Known people are green, strangers are red with a timer.
- **Unknown visitor alerts.** After a stranger stays in view for a set time, a photo is saved, an alert is created and an email is sent.
- **Authorized people.** Enrol someone by capturing 50 webcam photos. Only frames with exactly one clear face are kept.
- **Dashboard** with live counts, a 7-day activity chart and recent events.
- **Security logs** with search, filters and CSV export.
- **Admin accounts** with registration and password reset by email code (OTP), hashed passwords and a change-password page.
- Light and dark themes, and a layout that works on phones. No external libraries are loaded.

## How it works

1. **Detect:** OpenCV Haar Cascade finds faces in each video frame.
2. **Embed:** DeepFace turns each face into an ArcFace embedding (a list of numbers describing the face).
3. **Classify:** with two or more people enrolled, an SVM predicts who it is. The face must also be close (cosine distance) to that person's stored faces, otherwise it counts as unknown. With one person enrolled, only the distance check is used.
4. **Alert:** if an unknown face stays in view for `UNKNOWN_SECONDS`, the frame is saved, logged, and emailed to the admin.

## Tech stack

| Part | Tools |
|---|---|
| Backend | Python, Flask |
| Database | MySQL |
| Computer vision | OpenCV (Haar Cascade) |
| Face recognition | DeepFace with ArcFace, scikit-learn SVM |
| Frontend | HTML, CSS, JavaScript (no frameworks, works offline) |

## Project structure

```
securehome/
├── app.py                  # Flask app, routes, camera worker, settings
├── ml_pipeline/
│   ├── __init__.py
│   └── face_engine.py      # embeddings, SVM training, identification
├── templates/              # Jinja pages (dashboard, camera, users, alerts, logs, ...)
├── static/
│   ├── css/style.css       # design system
│   └── js/app.js           # theme, toasts, dialogs
├── haarcascade_frontalface_default.xml
├── local_settings.example.py
├── test_email.py           # checks your Gmail settings
└── requirements.txt
```

## Setup

**You need:** Python 3.9 to 3.11, a running MySQL server, and a webcam.

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

### Configure your private settings

Copy the example file and fill in your real values. `local_settings.py` is git-ignored, so your passwords never reach GitHub.

```bash
copy local_settings.example.py local_settings.py      # Windows
# cp local_settings.example.py local_settings.py      # macOS / Linux
```

| Setting | Meaning |
|---|---|
| `SECRET_KEY` | Long random string. Generate one: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DB_PASSWORD` | Your MySQL root password (change `DB_HOST`, `DB_USER`, `DB_NAME` in `app.py` if needed) |
| `SENDER_EMAIL` | Gmail address that sends alerts and codes |
| `SENDER_PASSWORD` | Gmail **app password** (16 letters), not your normal password |
| `DEFAULT_ADMIN_EMAIL` | Where alert emails are delivered |
| `UNKNOWN_SECONDS` | Seconds a stranger must stay in view before an alert (default 5) |
| `ALERT_COOLDOWN_SECONDS` | Minimum wait between two alerts (default 60) |
| `CAMERA_INDEX` | `0` for the default webcam, `1` for an external one |

**Getting a Gmail app password:** turn on 2-Step Verification in your Google account, then open <https://myaccount.google.com/apppasswords>, create a password and paste it in. Run `python test_email.py` to confirm it works.

### Run

```bash
python app.py
```

The database, tables and a default admin are created automatically, and your browser opens at <http://127.0.0.1:5000>.

> The first run downloads the ArcFace model (about 130 MB), so you need internet once. After that it works offline.

### Default admin

| Username | Password |
|---|---|
| `admin` | `admin123` |

**Change this password** in *My profile* straight after your first login.

## Using it

1. Log in and open **Authorized people**. Add yourself and the people who live with you.
2. Open **Live camera**. Recognised people are logged. Strangers get a timer, then an alert.
3. Review photos under **Unknown visitors**, and the full history under **Security logs**.

## Limitations

This is a learning project, and it has real limits:

- **Needs several people enrolled.** With only one person enrolled, the system has nobody to compare against and can label every visitor as that person. Enrol 5 to 6 people or more for a reliable known/unknown split.
- **Lookalikes can be confused**, such as relatives and siblings, especially with few photos.
- **Needs a clear, front-facing view.** Haar Cascade detection misses side angles, masks, caps, sunglasses, dark rooms and faces far from the camera.
- **No liveness detection.** A photo or phone screen of an enrolled person may be accepted.
- **Only watches while the Live camera page is open.** It is not a 24/7 background service.
- **One local webcam.** IP cameras, CCTV and RTSP streams are not supported.
- **Email alerts need internet** and a Gmail app password.
- **Speed depends on your computer.** Recognition runs on the CPU, so older laptops may lag.
- **Not hardened for the internet.** It uses the Flask development server without HTTPS. Use it on your home network only.
- **Not a certified security system.** Do not rely on it as your only protection.

## Privacy and security notes

- Face photos and trained models are stored locally in `CollectedImages/`, which is git-ignored. Never upload that folder.
- Passwords are hashed. Email codes expire after 10 minutes with 5 attempts. Forms use CSRF tokens, and each admin can only open their own images.
- Keep `local_settings.py` private. If a password ever leaks, revoke it and create a new one.

## Ideas for future work

Liveness detection, a stronger face detector (such as RetinaFace), enrolment quality checks, IP camera support, Docker setup, and push or SMS alerts.

## Author

**Md Sakir Jalal** · shakirjalal44@gmail.com
