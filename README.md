🌌 HINA: High-Intelligence Network Assistant

HINA is an advanced, modular AI assistant designed to bridge the gap between Large Language Models and local system control. Built with a "Guard-Brain" architecture, HINA doesn't just chat—she executes. From managing local music databases to performing autonomous web research, HINA acts as a central nervous system for your digital life.

🚀 Key Features

🛡️ The Guard Model (Intent Routing)

Unlike standard bots, HINA uses a specialized "Guard" classifier. Every user query is first analyzed by a low-latency model to determine the correct execution path:

music: Triggers local media playback logic.

web: Initiates autonomous web scraping and research.

code: Handles system-level tasks and file operations.

chat: Standard conversational mode with a human-like personality.

🧠 Persistent Neural Memory

HINA utilizes a MySQL backend to store long-term conversations.

Agentic Summarization: A dedicated background agent (summarizer.py) processes historical data.

Contextual Recall: HINA remembers past interactions with "Sourav," allowing her to reference previous topics naturally during conversation.

🎵 Intelligent Music System

Fuzzy Search: Uses rapidfuzz to find songs in a local mass storage DB even with typos.

LLM Ranking: If multiple matches are found, a secondary LLM determines the most likely intended track.

Native Playback: Seamlessly controls mpv for background audio.

🌐 Autonomous Research Pipeline

When asked about current events, HINA:

Expands your query into multiple search permutations.

Scrapes DuckDuckGo and individual websites.

Synthesizes thousands of words of "raw web" data into a concise, cited answer.

🗣️ Neural TTS & STT

STT: Efficient speech-to-text with fuzzy wake-word detection ("Hina").

TTS: Powered by Piper (ONNX) using high-quality voices like en_US-amy-medium for natural, low-latency speech synthesis.

🛠️ Project Structure

File

Description

body_hina.py

The main entry point. Handles wake-word detection and Intent Guard routing.

hina_brain.py

The core LLM logic. Manages personality, prompt engineering, and memory injection.

music_system.py

Local library indexing, fuzzy matching, and mpv control.

raw_web.py

Multi-step research pipeline (search, scrape, and extract).

summarizer.py

Agentic memory processor that turns SQL rows into "memories."

pipe_tts.py

TTS engine configuration for the Piper ONNX models.

⚙️ Installation & Setup

1. Prerequisites

Python 3.9+

MySQL Server (Running with a Hina database and short_memo table)

External Tools: mpv (for music), piper (for voice)

2. Environment Variables (.env)

api_hina="your_groq_api_key"
hinasum="your_groq_api_key_for_summarizer"
user="mysql_username"
pass="mysql_password"
personal="Your_Detailed_Hina_Personality_Prompt"


3. Install Dependencies

pip install groq rapidfuzz mysql-connector-python beautifulsoup4 requests python-dotenv piper-tts


🔮 Roadmap: The "God-Mode" Update

HINA is rapidly evolving. The following features are currently in development:

👁️ Vision System: Camera integration using OpenCV to recognize objects and "watch" the real world.

📸 Proactive Troubleshooting: Automated screenshot analysis to detect when the user is struggling with code and offer solutions unprompted.

⌨️ Full PC Control: Direct system manipulation using pyautogui.

🖐️ Gesture Control: Hand-tracking via MediaPipe to control volume and windows.

👨‍💻 About the Developer

Sourav | 17-year-old Developer 🚀

🔭 Currently: Building HINA to be the ultimate autonomous companion.

🤝 Seeking: Collaboration on improving code efficiency and LLM agentic workflows.

🌱 Learning: AI Architecture + MERN Stack.

⚡ Fun Fact: "I’m 17 — still figuring life out, but already coding like it’s my first language."

💬 Connect

GitHub: souravdpal

Interests: 🧠 AI, ⚙️ Full-Stack, 🌌 Space & Quantum Physics, 🛡️ Cybersecurity.

"Building the future, one function at a time."