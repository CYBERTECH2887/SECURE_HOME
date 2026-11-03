# SecureHome - Advanced Face Recognition Security System

SecureHome is an advanced, offline, and self-contained face-recognition-based smart home surveillance and workspace management system. Built for high accuracy and robust security, it operates entirely locally without relying on external cloud APIs.

---

## 🚀 Key Features

* **Advanced Face Recognition**: Powered by the **ArcFace** deep learning model with facial alignment (`align=True`) via DeepFace and classified using **Scikit-Learn SVM**.


* **Live Video Monitoring**: Real-time video feed via OpenCV with smart bounding boxes, confidence thresholding, and automated entry logging.


* **Automated Unknown Visitor Alerts**: Captures continuous frames of unknown visitors and sends instant email alerts with attached photos running on a background worker thread.


* **Multi-Tenant Admin Workspace**: Isolated administrator accounts, profile management, and role-based access control (Home Owner, Family Member, Trusted Visitor, Relative, Others).


* **Secure Authentication**:
* Password hashing using **Werkzeug Security**.


* Email-based **6-digit OTP verification** for new admin registration and password recovery.




* **Comprehensive Logging & Management**: Detailed security event logs with a built-in "Clear Logs" option and CRUD operations for managing authorized users.


* **Dynamic Theme Toggle**: Seamless light and dark mode switching across all pages with local storage persistence.


* **100% Offline & Independent**: Runs entirely self-contained using a local MySQL database and Python runtime.



---

## 🛠️ Tech Stack

* **Backend**: Python, Flask


* **Computer Vision & AI**: OpenCV, DeepFace (ArcFace), Scikit-Learn (SVM), NumPy


* **Database**: MySQL (Relational Schema with automated table creation)


* **Frontend**: HTML5, CSS3 (Glassmorphic UI design), JavaScript


* **Notifications**: Python `smtplib` (SMTP Email Integration)



---

## ⚙️ Installation & Setup

1. **Clone the Repository**:
```bash
git clone https://github.com/YOUR_USERNAME/SecureHome-Advanced.git
cd SecureHome-Advanced

```


2. **Create and Activate a Virtual Environment**:
```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

```


3. **Install Dependencies**:
Ensure you have all required machine learning and web packages installed:
```bash
pip install flask opencv-python deepface scikit-learn numpy mysql-connector-python

```


4. **Configure Database and Email**:
* Ensure your local MySQL server is running (default credentials: user `root`, password `mysql`).


* Update your sender email and app password inside `app.py` under the **EMAIL CONFIGURATION** section if you wish to use live alert and OTP emails.




5. **Run the Application**:
```bash
python app.py

```


The application will automatically initialize the MySQL database/tables and launch your default browser to `[http://127.0.0.1:5000/](http://127.0.0.1:5000/)`.



---

## 💻 Usage Guide

1. **Landing Page**: View the project specifications, overview, and access the feedback form or admin login/registration portals.


2. **Register**: Create an administrator workspace by filling out your profile details and verifying your email address via the 6-digit OTP.


3. **Dashboard**: Monitor active authorized profile counts, pending unknown visitor alerts, and recent security logs.


4. **Authorized Users**: Register family members or trusted visitors by capturing 50 continuous face frames offline to train the ArcFace model.


5. **Live Camera**: Monitor real-time streaming, automated recognition, and unknown intrusion alerts.



---

## 📞 Contact & Support

* **Developed by**: Shakir Jalal


* **Email**: shakirjalal44@gmail.com


* **Phone**: +91 XXXXX XXXXX
