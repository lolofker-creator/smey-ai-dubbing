import subprocess
import tempfile
from pathlib import Path

import requests
import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg

st.set_page_config(page_title="Smey AI Dubbing", page_icon="🎙️")
st.title("🎙️ Smey AI Dubbing")
st.caption("វីដេអូចិន → បកប្រែខ្មែរ → AI សំឡេងខ្មែរ → MP4")

uploaded = st.file_uploader("🎥 ជ្រើសវីដេអូ", type=["mp4", "mov", "mkv", "webm", "avi"])
voice_label = st.selectbox("🎙️ ជ្រើសសំឡេងខ្មែរ", ["Sovann", "Puthi"])
voice = "sovann" if voice_label == "Sovann" else "puthi"

if uploaded and st.button("🇰🇭 បង្កើត AI Dubbing", type="primary", use_container_width=True):
    gemini_key = st.secrets.get("GEMINI_API_KEY", "")
    doslarb_key = st.secrets.get("DOSLARB_API_KEY", "")
    if not gemini_key or not doslarb_key:
        st.error("សូមដាក់ GEMINI_API_KEY និង DOSLARB_API_KEY ក្នុង Streamlit Secrets")
        st.stop()

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        video = td / "input.mp4"
        audio = td / "audio.mp3"
        khmer_audio = td / "khmer.mp3"
        output = td / "smey_ai_dubbing.mp4"
        video.write_bytes(uploaded.getbuffer())
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        st.write("1️⃣ កំពុងស្តាប់សំឡេងចិន...")
        subprocess.run([ffmpeg, "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        client = genai.Client(api_key=gemini_key)
        audio_file = client.files.upload(file=str(audio), config={"mime_type": "audio/mpeg"})
        interaction = client.interactions.create(
            model="gemini-3.5-transcribe",
            input=[{"type": "audio", "uri": audio_file.uri, "mime_type": audio_file.mime_type}],
            generation_config={"transcription_config": {
                "language_codes": ["zh-CN"], "mode": {"type": "verbatim"}
            }},
        )
        chinese = (interaction.output_text or "").strip()
        if not chinese:
            st.error("មិនរកឃើញសំឡេងនិយាយ")
            st.stop()

        st.write("2️⃣ កំពុងបកប្រែជាខ្មែរ...")
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=f"Translate this spoken Chinese into natural conversational Khmer. Return only Khmer translation.\n\n{chinese}",
            config=types.GenerateContentConfig(temperature=0.2),
        )
        khmer = (response.text or "").strip()
        if not khmer:
            st.error("បកប្រែមិនបាន")
            st.stop()
        if len(khmer) > 1200:
            st.error("អត្ថបទខ្មែរលើស 1200 តួអក្សរ។ ជំហាននេះត្រូវបែងចែកជាផ្នែកសិន។")
            st.stop()

        st.write("3️⃣ កំពុងបង្កើតសំឡេង AI ខ្មែរ...")
        r = requests.post(
            "https://doslarb.cloud/api/v1/tts",
            headers={"Authorization": f"Bearer {doslarb_key}", "Content-Type": "application/json"},
            json={"text": khmer, "voice": voice},
            timeout=120,
        )
        if not r.ok:
            st.error(f"Doslarb TTS error {r.status_code}: {r.text}")
            st.stop()
        khmer_audio.write_bytes(r.content)

        st.write("4️⃣ កំពុងដាក់សំឡេងខ្មែរចូលវីដេអូ...")
        subprocess.run([
            ffmpeg, "-y", "-i", str(video), "-i", str(khmer_audio),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
            str(output)
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        st.success("🎉 រួចរាល់! វីដេអូមានសំឡេងខ្មែរ AI")
        st.download_button("⬇️ ទាញយក MP4", output.read_bytes(), "smey_ai_dubbing.mp4", "video/mp4",
                           use_container_width=True)
