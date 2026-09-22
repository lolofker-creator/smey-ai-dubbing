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
st.caption("វីដេអូចិន → បកប្រែខ្មែរ → សំឡេងខ្មែរ តាមពេលនិយាយ → MP4")


uploaded = st.file_uploader(
    "🎥 ជ្រើសវីដេអូ",
    type=["mp4", "mov", "mkv", "webm", "avi"]
)

voice_label = st.selectbox(
    "🎙️ ជ្រើសសំឡេងខ្មែរ",
    ["Sovann", "Puthi"]
)

voice = "sovann" if voice_label == "Sovann" else "puthi"


def get_seconds(value):
    if value is None:
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if text.endswith("ms"):
        return float(text[:-2]) / 1000

    if text.endswith("s"):
        return float(text[:-1])

    return float(text)


def get_word_annotations(interaction):
    words = []

    for step in getattr(interaction, "steps", []) or []:
        for content in getattr(step, "content", []) or []:
            for annotation in getattr(content, "annotations", []) or []:
                if getattr(annotation, "type", None) == "word_info":
                    words.append(annotation)

    return words


def make_segments(words, max_words=8):
    segments = []

    current_text = []
    current_start = None
    current_end = None

    for word in words:

        text = str(getattr(word, "text", "")).strip()

        if not text:
            continue

        start = get_seconds(getattr(word, "start_offset", 0))
        end = get_seconds(getattr(word, "end_offset", 0))

        if current_start is None:
            current_start = start

        current_text.append(text)
        current_end = end

        if (
            len(current_text) >= max_words
            or text.endswith(("。", "！", "？", ".", "!", "?"))
        ):
            segments.append({
                "text": " ".join(current_text),
                "start": current_start,
                "end": current_end
            })

            current_text = []
            current_start = None
            current_end = None

    if current_text:
        segments.append({
            "text": " ".join(current_text),
            "start": current_start,
            "end": current_end
        })

    return segments


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
        output = td / "smey_ai_dubbing.mp4"

        video.write_bytes(uploaded.getbuffer())

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        # =========================
        # 1. Extract audio
        # =========================

        st.write("1️⃣ កំពុងស្តាប់សំឡេងចិន និងរកពេលនិយាយ...")

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
        # 2. Transcribe with timestamps
        # =========================

        interaction = None

        for attempt in range(3):

            try:

                interaction = client.interactions.create(
                    model="gemini-3.5-transcribe",
                    input=[
                        {
                            "type": "audio",
                            "uri": audio_file.uri,
                            "mime_type": audio_file.mime_type,
                        }
                    ],
                    generation_config={
                        "transcription_config": {
                            "language_codes": ["cmn-Hans-CN"],
                            "mode": {
                                "type": "verbatim",
                                "timestamp_granularities": ["word"],
                            },
                        }
                    }
                )

                break

            except Exception as e:

                if attempt < 2:
                    time.sleep(8)
                else:
                    st.error(
                        "Gemini មិនអាចស្តាប់សំឡេងបាននៅពេលនេះ។"
                    )
                    st.stop()

        words = get_word_annotations(interaction)

        if not words:
            st.error(
                "Gemini មិនបានផ្តល់ timestamp សម្រាប់សំឡេង។"
            )
            st.stop()

        segments = make_segments(words, max_words=8)

        if not segments:
            st.error("រកមិនឃើញការនិយាយក្នុងវីដេអូ។")
            st.stop()

        st.write(
            f"រកឃើញការនិយាយចំនួន {len(segments)} ផ្នែក"
        )

        # =========================
        # 3. Translate each segment
        # =========================

        st.write("2️⃣ កំពុងបកប្រែជាខ្មែរ តាមផ្នែក...")

        translated_segments = []

        for index, segment in enumerate(segments):

            chinese = segment["text"]

            khmer = ""

            for attempt in range(2):

                try:

                    response = client.models.generate_content(
                        model="gemini-3.8-flash",
                        contents=(
                            "Translate this spoken Chinese into "
                            "natural conversational Khmer. "
                            "Keep it short enough to fit approximately "
                            "the same speaking time. "
                            "Return ONLY Khmer.\n\n"
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

            if not khmer:

                for fallback_model in [
                    "gemini-3.7-flash",
                    "gemini-3.6-flash",
                    "gemini-3.5-flash"
                ]:

                    try:

                        response = client.models.generate_content(
                            model=fallback_model,
                            contents=(
                                "Translate this spoken Chinese "
                                "into natural conversational Khmer. "
                                "Return ONLY Khmer.\n\n"
                                f"{chinese}"
                            )
                        )

                        khmer = (response.text or "").strip()

                        if khmer:
                            break

                    except Exception:
                        continue

            if not khmer:
                st.error(
                    f"បកប្រែផ្នែកទី {index + 1} មិនបាន។"
                )
                st.stop()

            translated_segments.append({
                "text": khmer,
                "start": segment["start"],
                "end": segment["end"]
            })

        # =========================
        # 4. Generate Khmer voices
        # =========================

        st.write("3️⃣ កំពុងបង្កើតសំឡេង AI ខ្មែរ...")

        segment_audio_files = []

        for index, segment in enumerate(translated_segments):

            text = segment["text"]

            if len(text) > 1200:
                st.error(
                    f"ផ្នែកទី {index + 1} លើស 1200 តួអក្សរ។"
                )
                st.stop()

            r = requests.post(
                "https://doslarb.cloud/api/v1/tts",
                headers={
                    "Authorization": f"Bearer {doslarb_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "text": text,
                    "voice": voice
                },
                timeout=120
            )

            if not r.ok:
                st.error(
                    f"Doslarb TTS error {r.status_code}"
                )
                st.stop()

            segment_file = td / f"segment_{index}.mp3"
            segment_file.write_bytes(r.content)

            segment_audio_files.append(segment_file)

        # =========================
        # 5. Create silent timeline
        # =========================

        st.write(
            "4️⃣ កំពុងតម្រឹមសំឡេងខ្មែរតាមពេលនិយាយ..."
        )

        # Get video duration
        probe = subprocess.run(
            [
                ffmpeg,
                "-i",
                str(video)
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        import re

        match = re.search(
            r"Duration:\s*(\d+):(\d+):([\d.]+)",
            probe.stderr
        )

        if not match:
            st.error("មិនអាចរកប្រវែងវីដេអូបាន។")
            st.stop()

        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = float(match.group(3))

        video_duration = (
            hours * 3600
            + minutes * 60
            + seconds
        )

        # Create each delayed audio track
        delayed_tracks = []

        for index, segment in enumerate(translated_segments):

            start_ms = int(segment["start"] * 1000)

            delayed = td / f"delayed_{index}.wav"

            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(segment_audio_files[index]),
                    "-af",
                    f"adelay={start_ms}|{start_ms}",
                    str(delayed)
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE
            )

            delayed_tracks.append(delayed)

        # =========================
        # 6. Mix all Khmer voices
        # =========================

        mixed_audio = td / "khmer_final.wav"

        inputs = []

        for track in delayed_tracks:
            inputs.extend(["-i", str(track)])

        filter_parts = []

        for i in range(len(delayed_tracks)):
            filter_parts.append(f"[{i}:a]")

        filter_complex = (
            "".join(filter_parts)
            + f"amix=inputs={len(delayed_tracks)}:"
              "duration=longest:dropout_transition=0,"
              "volume=1"
        )

        subprocess.run(
            [
                ffmpeg,
                "-y",
                *inputs,
                "-filter_complex",
                filter_complex,
                "-t",
                str(video_duration),
                str(mixed_audio)
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )

        # =========================
        # 7. Put Khmer audio into video
        # =========================

        st.write(
            "5️⃣ កំពុងបញ្ចូលសំឡេងខ្មែរទៅក្នុងវីដេអូ..."
        )

        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(video),
                "-i",
                str(mixed_audio),
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
                "-t",
                str(video_duration),
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
            "🎉 រួចរាល់! សំឡេងខ្មែរត្រូវបានតម្រឹមតាមពេលនិយាយ"
        )

        st.download_button(
            "⬇️ ទាញយក MP4",
            output.read_bytes(),
            "smey_ai_dubbing.mp4",
            "video/mp4",
            use_container_width=True
            )
