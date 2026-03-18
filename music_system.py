import os
import re
import json
import random
import subprocess
from rapidfuzz import fuzz
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# Configuration
MUSIC_DB = "/run/media/sourav/souravMain/massDB"
EXTENSIONS = ('.mp3', '.mp4', '.flac', '.wav', '.m4a', '.ogg')
# Media player to use (mpv, ffplay, or vlc)
PLAYER = "mpv" 

def clean_string(text):
    """Normalizes strings for better matching."""
    if not isinstance(text, str):
        return ""
    name = os.path.splitext(text)[0]
    name = re.sub(r'[^a-zA-Z0-9\s]', ' ', name).lower()
    return " ".join(name.split())

def get_music_files(db_path):
    """Recursively fetches all music file paths."""
    files = []
    if not os.path.exists(db_path):
        print(f"Error: Database path {db_path} not found.")
        return []
        
    for root, _, filenames in os.walk(db_path):
        for f in filenames:
            if f.lower().endswith(EXTENSIONS):
                files.append(os.path.join(root, f))
    return files

def predict_music(prompt, top_n=5):
    """Predicts best matching music files based on prompt."""
    all_paths = get_music_files(MUSIC_DB)
    if not all_paths:
        return []

    name_map = {}
    for path in all_paths:
        cleaned = clean_string(os.path.basename(path))
        if cleaned not in name_map:
            name_map[cleaned] = []
        name_map[cleaned].append(path)

    cleaned_prompt = clean_string(prompt)
    scored_results = []

    for cleaned_name in name_map.keys():
        p_ratio = fuzz.partial_ratio(cleaned_prompt, cleaned_name)
        w_ratio = fuzz.WRatio(cleaned_prompt, cleaned_name)
        exact_bonus = 50 if cleaned_prompt in cleaned_name else 0
        final_score = (p_ratio * 0.6) + (w_ratio * 0.4) + exact_bonus
        scored_results.append((cleaned_name, final_score))

    scored_results.sort(key=lambda x: x[1], reverse=True)
    
    predictions = []
    for match_text, score in scored_results[:top_n]:
        original_path = name_map[match_text][0] 
        predictions.append({
            "score": round(score, 2),
            "file_path": original_path,
            "display_name": os.path.basename(original_path)
        })
    return predictions

def play_music_logic(input_text: str):
    """
    Analyzes user intent with LLM and plays the predicted song.
    """
    # 1. Get fuzzy matches from DB
    list_music = predict_music(prompt=input_text, top_n=5)
    
    system_prompt = """
    You are a music analyzer. Your task is to pick the best file path from a provided list based on the user's request.
    Return ONLY a JSON object in this format:
    {"music": "/path/to/file"}
    
    If the user wants a random song or doesn't specify, return:
    {"music": "random"}
    """

    api_key = os.getenv("music_gen")
    client = Groq(api_key=api_key)
    
    # Use a valid Groq model name
    model = "llama-3.1-8b-instant" 

    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User Request: {input_text}\nTop Matches: {list_music}"}
            ],
            temperature=0
        )

        response_text = completion.choices[0].message.content.strip()
        
        # Simple JSON extraction (handles markdown blocks if LLM adds them)
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        
        data = json.loads(response_text)
        music_path = data.get("music")

        # 2. Handle "random" or specific path
        if music_path == "random":
            all_files = get_music_files(MUSIC_DB)
            if all_files:
                music_path = random.choice(all_files)
                print(music_path)
            else:
                print("Database is empty!")
                return

        # 3. Play the music
        if os.path.exists(music_path):
            print(f"Now Playing: {os.path.basename(music_path)}")
            # Runs the player in the background
            #from hina_brain import model_res
            #model_res(up=input_text,sec_data=f"Now Playing the song song name : {os.path.basename(music_path)}")
            subprocess.Popen([PLAYER, music_path])
        else:
            print(f"Error: File not found -> {music_path}")

    except Exception as e:
        print(f"System Error: {e}")

if __name__ == "__main__":
    query = input("What would you like to hear? ")
    if query.strip():
        play_music_logic(query)