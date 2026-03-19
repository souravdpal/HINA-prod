import speech_recognition as sr

class VoiceRecognizer:
    def __init__(self, pause_duration=1.5):
        self.recognizer = sr.Recognizer()
        
        # How many seconds of silence it waits before assuming you finished your sentence.
        # 1.5 to 2.0 is usually the sweet spot.
        self.recognizer.pause_threshold = pause_duration
        
        # We turn this back ON so it automatically figures out your background noise level,
        # preventing it from getting stuck listening to your computer fans.
        self.recognizer.dynamic_energy_threshold = True

    def listen_and_transcribe(self):
        """
        Listens to the mic until the user stops speaking, transcribes it, 
        and returns the text as a string. Returns an empty string if nothing is heard.
        """
        with sr.Microphone() as source:
            # Calibrate to current background noise for 1 second before opening the mic
            self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
            
            try:
                # timeout=10: It will give up if you don't START talking within 10 seconds.
                # phrase_time_limit=None: Once you start talking, there is no time limit.
                audio_data = self.recognizer.listen(source, timeout=10, phrase_time_limit=None)
                
                # Send the clean audio to Google
                text = self.recognizer.recognize_google(audio_data)
                return text
                
            except sr.WaitTimeoutError:
                # You didn't say anything within 10 seconds
                return ""
            except sr.UnknownValueError:
                # It heard noise but couldn't make out any words
                return ""
            except sr.RequestError as e:
                # Internet or Google API issue
                print(f"[Network Error] {e}")
                return ""