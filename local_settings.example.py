# Copy this file to local_settings.py and fill in your real values.
# local_settings.py is git-ignored, so your passwords never reach GitHub.
# Generate a secret key with:  python -c "import secrets; print(secrets.token_hex(32))"
CONFIG = {
    'SECRET_KEY': 'paste-a-long-random-string-here',
    'DB_PASSWORD': 'your-mysql-password',
    'SENDER_EMAIL': 'your-gmail@gmail.com',
    'SENDER_PASSWORD': 'your-16-letter-gmail-app-password',
    'DEFAULT_ADMIN_EMAIL': 'where-alert-emails-should-go@gmail.com',
    # Optional: 'DB_NAME', 'CAMERA_INDEX', 'UNKNOWN_SECONDS', 'ALERT_COOLDOWN_SECONDS', 'DEFAULT_ADMIN_PASSWORD' ...
}
