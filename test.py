from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello_world():
    return "Hello, World!"
def run_server():
    print("Server running on port 8000...")
    app.run(port=8000)
if __name__ == "__main__":
    run_server()