"""OceanGuard AI — Configuration"""
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

AIS_API_KEY:   str = os.getenv("AIS_API_KEY", "").strip()
AIS_PROVIDER:  str = os.getenv("AIS_PROVIDER", "demo").strip()
HOST:          str = os.getenv("HOST", "0.0.0.0")
PORT:          int = int(os.getenv("PORT", "8000"))
POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "3"))
MAX_VESSELS:   int = int(os.getenv("MAX_VESSELS", "20000"))
DATABASE_URL:  str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/oceanguard")
CORS_ORIGINS: list[str] = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:5500,http://localhost:5500,null"
).split(",")
