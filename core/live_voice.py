from core.stt_server import SpeechToText
from hina_brain import Hina_res


stt=SpeechToText(model_size="base.en")

def get_voice_inpu():
    text=stt.listen(timeout=10)
    print(text)
    return text


Hina_res(
    query=get_voice_inpu(),
)