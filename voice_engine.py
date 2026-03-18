import edge_tts
import asyncio
import subprocess as sub
import time
import os 

async def gen_voice(text, output_file="female_voice.mp3"):
    voice = "hi_IN-priyamvada-medium"  # natural female voice
    tts = edge_tts.Communicate(text, voice)
    await tts.save(output_file)
    print(f"Saved as {output_file}")

text = "सौरमंडल में सूर्य, आठ ग्रह, बौने ग्रह, 200 से अधिक चंद्रमा और असंख्य क्षुद्रग्रह एवं धूमकेतु शामिल हैं, जो सभी हमारे केंद्रीय तारे की परिक्रमा करते हैं। 4.6 अरब वर्ष पूर्व निर्मित यह सौरमंडल मिल्की वे आकाशगंगा के ओरियन आर्म में स्थित है। सूर्य, एक जी-प्रकार का मुख्य अनुक्रम तारा है, जिसका कुल द्रव्यमान 99.8% है।"
asyncio.run(gen_voice(text))