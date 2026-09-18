import os


SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

SQLALCHEMY_DATABASE_URI = (
    "sqlite:////app/superset_home/superset.db"
)

WTF_CSRF_ENABLED = True

TALISMAN_ENABLED = False

ENABLE_PROXY_FIX = False

ROW_LIMIT = 50_000

FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
}