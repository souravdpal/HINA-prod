# HINA

<p align="center">
  <b>Personal AI Assistant built from scratch</b><br>
  Voice • Automation • Intelligence • System Control
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue?style=flat-square"/>
  <img src="https://img.shields.io/badge/linux-arch-important?style=flat-square"/>
  <img src="https://img.shields.io/badge/status-active-success?style=flat-square"/>
</p>

---

## Overview

HINA is a fully custom-built personal AI assistant designed to **control systems, process voice, and interact intelligently**.  

It is not just a chatbot — it is a **modular system** combining:

- Speech Recognition (STT)
- Text-to-Speech (TTS)
- System Automation
- Web Interaction
- AI Processing

---

## Architecture
User (Voice / Input)
↓
Speech Engine (STT)
↓
HINA Brain (Processing / Logic)
↓
Modules (Web, Files, System, AI)
↓
Voice Engine (TTS Output)


---
├── hina_brain.py # Core logic
├── speech_engine.py # Speech-to-text
├── voice_engine.py # Text-to-speech
├── stt_module.py # STT handling
├── pipe_tts.py # TTS pipeline
├── web_crawler.py # Web scraping
├── summarizer.py # AI summarization
├── music_system.py # Media control
├── screen_live.py # Screen interaction
├── memo.py # Memory system
├── raw_web.py # Web raw handling
├── prompt_code.py # Prompt handling
├── package.json # Node.js dependencies
├── package-lock.json # Node.js lock file
├── *.onnx # Voice models
└── README.md # Project overview

## Features

- Voice-controlled interaction
- Real-time speech processing
- Modular, extendable architecture
- Web crawling & summarization
- System-level automation
- Custom AI logic (offline-ready)

---

## Tech Stack

- Python
- Node.js (for browser STT)
- ONNX models (offline voice)
- Linux (Arch-based environment)

---

## Setup

```bash
git clone https://github.com/your-username/hina.git
cd hina

pip install -r requirements.txt
npm install


Philosophy

HINA is built with a simple idea:

Control your system.
Understand your tools.
Don’t depend blindly.

Future Goals

Improve conversational intelligence

Persistent memory system

Full offline capability

GUI interface


Author

Sourav

<p align="center"> <i>Built with focus. No distractions.</i> </p> ```