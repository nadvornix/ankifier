from apikeys import *
from datetime import timedelta

PROFILES_PATH = "/home/jiri/ankifier_profiles/{ankiweb_username_base32}"

PERMANENT_SESSION_LIFETIME = timedelta(days=365 * 5)
SESSION_TYPE = "filesystem"
SESSION_FILE_THRESHOLD = 5000
