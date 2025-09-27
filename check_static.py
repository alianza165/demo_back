# check_static.py
import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'minimal.settings')
django.setup()

print("BASE_DIR:", settings.BASE_DIR)
print("STATIC_ROOT:", settings.STATIC_ROOT)
print("STATIC_URL:", settings.STATIC_URL)
print("DEBUG:", settings.DEBUG)

# Check if static files exist
static_admin_path = os.path.join(settings.STATIC_ROOT, 'admin')
print("Static admin path exists:", os.path.exists(static_admin_path))

if os.path.exists(static_admin_path):
    print("Contents of static admin:", os.listdir(static_admin_path)[:5])
