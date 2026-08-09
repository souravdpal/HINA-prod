from tomllib import load

from pyngrok import ngrok
import time
from dotenv import load_dotenv
import os 
load_dotenv()

ngrok.set_auth_token(os.getenv("ng_token"))

public_url = ngrok.connect(3000, domain="mowing-resistant-pamphlet.ngrok-free.dev")
print(f"Public URL: {public_url}")

try:
    # Keep the tunnel alive indefinitely
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Shutting down tunnel...")
    ngrok.disconnect(public_url)
    ngrok.kill()