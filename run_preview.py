"""Local preview launcher — boots the Flask app on port 5001 with SQLite fallback.
Not for production. Run: .preview-venv/bin/python run_preview.py
"""
import os
os.environ.pop("DATABASE_URL", None)  # force SQLite fallback for local preview
from app import app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)
