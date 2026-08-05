🌌 HINA V3 (Beta) — Autonomous System Entity

HINA is an advanced, high-performance autonomous agent operating over a Model Context Protocol (MCP) architecture. She is designed not just as a conversational AI, but as a deeply integrated system companion capable of executing code, scraping the web, managing media, and communicating through a real-time, low-latency text-to-speech pipeline.

✨ Core Features

🎙️ Real-Time Voice Pipeline (hin_voice_engine.py): Utilizes parallel processing with Piper TTS and Kokoro ONNX models for sub-second, natural voice synthesis (featuring customizable voices like Amy and Lessac).

🌐 Beautiful Web UI (localhost:3000): A custom Node.js frontend featuring rich Markdown rendering, dynamic image/video grids, and tool-invocation menus via @ mentions.

📡 "Live" Voice Interface: A dedicated acoustic interface (/live) with responsive audio visualizers and real-time STT/TTS streaming.

🧠 Advanced Routing Logic: Capable of maintaining deep contextual persona rules (v5.0) while dynamically deciding when to call external MCP tools or handle queries internally.

🛠️ The MCP Tool Ecosystem

HINA's intelligence is decoupled from her capabilities. She uses isolated MCP servers to interact with the world:

Tool

Capability

@web_search_mcp

Deep, live internet scraping and DuckDuckGo integration.

@astro_mcp

Fetches real-time space data, celestial events, and NASA API media grids.

@code_mcp

Code execution, database querying, and local environment management.

@youtube_mcp

Searches videos and extracts transcripts for RAG processing.

@github_mcp

Deep dives into repositories, issues, and Pull Requests.

@music_mcp

Local and web-based audio playback and management.

@imagine_mcp

On-the-fly AI image generation from text prompts.

@calendar_mcp

Schedule management and daily task tracking.

@msg_mcp

Reads, manages, and sends messages and emails.

🚀 Quick Start Guide

1. Environment Setup

Clone the system and initialize the dependency trees for both the Python Core and Node Server:

# 1. Setup Python Virtual Environment
python3 -m venv hina2
source hina2/bin/activate

# 2. Install Python Core Dependencies
pip install -r requirements.txt

# 3. Install Node.js Server Dependencies
npm install


2. Download ONNX Voice Models

HINA requires local ONNX weights for zero-latency TTS. Run these commands to pull the necessary engine files into the core/ directory:

cd core/

# Download Piper TTS Weights (Amy Medium)
wget -c https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en_US-amy-medium.onnx -O en_US-amy-medium.onnx
wget -c https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en_US-amy-medium.onnx.json -O en_US-amy-medium.onnx.json

# Download Piper TTS Weights (Lessac High)
wget -c https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en_US-lessac-high.onnx -O en_US-lessac-high.onnx
wget -c https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-en_US-lessac-high.onnx.json -O en_US-lessac-high.onnx.json

# Download Kokoro Core Weights
wget -c https://github.com/thewhitetulip/kokoro-onnx/releases/download/v0.1.0/kokoro-v1.0.onnx
wget -c https://github.com/thewhitetulip/kokoro-onnx/releases/download/v0.1.0/voices-v1.0.bin
cd ..


3. Booting the System

HINA runs in a decoupled architecture. You need to start the Web/WebSocket server and the Python core logic separately.

Terminal 1: Start the API & Frontend Server

node server.js


Server will initialize the database and listen on http://127.0.0.1:3000

Terminal 2: Ignite the Core Brain

source hina2/bin/activate
python core/hina_direct.py


The core will connect to the WebSocket and await instructions.

📂 System Architecture

core/: The central brain. Houses LLM routing (open_router.py, ollama_call.py), the voice engine (hin_voice_engine.py), memory state, and prompt injection.

mcp_servers/: Independent capability modules implementing the Model Context Protocol.

mcp_helper/: Low-level webdriver scripts and API wrappers (e.g., DuckDuckGo scraping, YouTube helpers) used by the MCP servers.

public/: The frontend static files (index.html, live.html, CSS, JS) served by Node.