from pyngrok import ngrok
import time

ngrok.set_auth_token("3ErkXe3zTdwIoVqq0uLdalNPrrU_5wTbzZZPVB5K7tUqeq11T")

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