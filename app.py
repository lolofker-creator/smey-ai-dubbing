import subprocess
import tempfile
import time
from pathlib import Path

import requests
import streamlit as st
from google import genai
from google.genai import types
import imageio_ffmpeg


st.set_page_config(
    page_title="Smey AI Dubbing",
    page_icon="🎙️"
)

st.title("🎙️ Smey AI Dubbing")
st.caption("វីដេអូចិន → បកប្រែខ្មែរ → AI សំឡេងខ្មែរ → MP4")


uploaded = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=["mp4", "mov", "mkv", "webm", "avi"]
)

voice_label = st.selectbox(
    "🎙️ ជ្រើសសំឡេងខ្មែរ",
    ["Sovann", "Puthi"]
)

voice = "sovann" if voice_label == "Sovann" else "puthi"


if uploaded and st.button(
    "🇰🇭 បង្កើត AI Dubbing",
    type="primary",
    use_container_width=True
):

    gemini_key = st.secrets.get("GEMINI_API_KEY", "")
    doslarb_key = st.secrets.get("DOSLARB_API_KEY", "")

    if not gemini_key or not doslarb_key:
        st.error(
            "សូមដាក់ GEMINI_API_KEY និង DOSLARB_API_KEY ក្នុង Streamlit Secrets"
        )
        st.stop()

    with tempfile.TemporaryDirectory() as temp_dir:

        td = Path(temp_dir)

        video = td / "input.mp4"
        audio = td / "audio.mp3"
        khmer_audio = td / "khmer.mp3"
        output = td / "smey_ai_dubbing.mp4"

        video.write_bytes(uploaded.getbuffer())

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        # =========================
        # 1. Extract audio
        # =========================

        st.write("1️⃣ កំពុងស្តាប់សំឡេងចិន...")

        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(audio)
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )

        client = genai.Client(api_key=gemini_key)

        audio_file = client.files.upload(
            file=str(audio),
            config={"mime_type": "audio/mpeg"}
        )

        # =========================
        # 2. Chinese transcription
        # =========================

        transcription_models = [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
        ]

        chinese = ""

        for model_name in transcription_models:

            for attempt in range(2):

                try:

                    response = client.models.generate_content(
                        model=model_name,
                        contents=[
                            (
                                "Listen to this audio carefully. "
                                "Transcribe ONLY the spoken Chinese words. "
                                "Do not translate. "
                                "Return only the Chinese transcript."
                            ),
                            audio_file
                        ],
                        config=types.GenerateContentConfig(
                            temperature=0.1
                        )
                    )

                    chinese = (response.text or "").strip()

                    if chinese:
                        break

                except Exception:
                    if attempt == 0:
                        time.sleep(5)
                    else:
                        continue

            if chinese:
                break

        if not chinese:
            st.error(
                "Gemini មិនអាចស្តាប់សំឡេងចិនបាននៅពេលនេះ។ "
                "សូមសាកម្តងទៀតក្រោយបន្តិច។"
            )
            st.stop()

        # =========================
        # 3. Translate Chinese → Khmer
        # =========================

        st.write("2️⃣ កំពុងបកប្រែជាខ្មែរ...")

        translation_models = [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
        ]

        khmer = ""

        for model_name in translation_models:

            for attempt in range(2):

                try:

                    response = client.models.generate_content(
                        model=model_name,
                        contents=(
                            "Translate this spoken Chinese into "
                            "natural conversational Khmer. "
                            "Keep the original meaning and tone. "
                            "Return ONLY Khmer translation.\n\n"
                            f"{chinese}"
                        ),
                        config=types.GenerateContentConfig(
                            temperature=0.2
                        )
                    )

                    khmer = (response.text or "").strip()

                    if khmer:
                        break

                except Exception:
                    if attempt == 0:
                        time.sleep(5)
                    else:
                        continue

            if khmer:
                break

        if not khmer:
            st.error(
                "Gemini មិនអាចបកប្រែបាននៅពេលនេះ។ "
                "សូមសាកម្តងទៀត។"
            )
            st.stop()

        if len(khmer) > 1200:
            st.error(
                "អត្ថបទខ្មែរលើស 1200 តួអក្សរ។ "
                "វីដេអូវែងត្រូវបែងចែកជាផ្នែកសិន។"
            )
            st.stop()

        # =========================
        # 4. Khmer AI Voice
        # =========================

        st.write("3️⃣ កំពុងបង្កើតសំឡេង AI ខ្មែរ...")

        r = requests.post(
            "https://doslarb.cloud/api/v1/tts",
            headers={
                "Authorization": f"Bearer {doslarb_key}",
                "Content-Type": "application/json"
            },
            json={
                "text": khmer,
                "voice": voice
            },
            timeout=120
        )

        if not r.ok:
            st.error(
                f"Doslarb TTS error {r.status_code}: {r.text}"
            )
            st.stop()

        khmer_audio.write_bytes(r.content)

        # =========================
        # 5. Replace video audio
        # =========================

        st.write("4️⃣ កំពុងដាក់សំឡេងខ្មែរចូលវីដេអូ...")

        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video),
                "-i",
                str(khmer_audio),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(output)
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )

        # =========================
        # Finished
        # =========================

        st.success(
            "🎉 រួចរាល់! វីដេអូមានសំឡេងខ្មែរ AI"
        )

        st.download_button(
            "⬇️ ទាញយក MP4",
            output.read_bytes(),
            "smey_ai_dubbing.mp4",
            "video/mp4",
            use_container_width=True
        )
