import subprocess
import tempfile
import time
import re
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


# =========================================================
# Convert Gemini timestamp values to seconds
# =========================================================

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

    try:
        return float(text)
    except Exception:
        return 0.0


# =========================================================
# Get word timestamps from Gemini
# =========================================================

def get_word_annotations(interaction):

    words = []

    for step in getattr(interaction, "steps", []) or []:

        for content in getattr(step, "content", []) or []:

            for annotation in getattr(
                content,
                "annotations",
                []
            ) or []:

                if getattr(
                    annotation,
                    "type",
                    None
                ) == "word_info":

                    words.append(annotation)

    return words


# =========================================================
# Group words into small speaking segments
# =========================================================

def make_segments(words, max_words=8):

    segments = []

    current_text = []
    current_start = None
    current_end = None

    for word in words:

        text = str(
            getattr(word, "text", "")
        ).strip()

        if not text:
            continue

        start = get_seconds(
            getattr(
                word,
                "start_offset",
                0
            )
        )

        end = get_seconds(
            getattr(
                word,
                "end_offset",
                0
            )
        )

        if current_start is None:
            current_start = start

        current_text.append(text)
        current_end = end

        if (
            len(current_text) >= max_words
            or text.endswith(
                ("。", "！", "？", ".", "!", "?")
            )
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


# =========================================================
# Main
# =========================================================

if uploaded and st.button(
    "🇰🇭 បង្កើត AI Dubbing",
    type="primary",
    use_container_width=True
):

    gemini_key = st.secrets.get(
        "GEMINI_API_KEY",
        ""
    )

    doslarb_key = st.secrets.get(
        "DOSLARB_API_KEY",
        ""
    )

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

        video.write_bytes(
            uploaded.getbuffer()
        )

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()


        # =================================================
        # 1. Extract audio
        # =================================================

        st.write(
            "1️⃣ កំពុងស្តាប់សំឡេងចិន និងរកពេលនិយាយ..."
        )

        try:

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

        except Exception as e:

            st.error(
                "មិនអាចដកសំឡេងចេញពីវីដេអូបានទេ។"
            )

            st.code(str(e))

            st.stop()


        # =================================================
        # Gemini client
        # =================================================

        try:

            client = genai.Client(
                api_key=gemini_key
            )

        except Exception as e:

            st.error(
                "មិនអាចភ្ជាប់ Gemini បានទេ។"
            )

            st.code(str(e))

            st.stop()


        # =================================================
        # Upload audio
        # =================================================

        try:

            audio_file = client.files.upload(
                file=str(audio),
                config={
                    "mime_type": "audio/mpeg"
                }
            )

        except Exception as e:

            st.error(
                "Gemini មិនអាច Upload សំឡេងបានទេ។"
            )

            st.code(
                f"{type(e).__name__}: {str(e)}"
            )

            st.stop()


        # =================================================
        # 2. Transcribe with word timestamps
        # =================================================

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

                            "language_codes": [
                                "cmn-Hans-CN"
                            ],

                            "mode": {
                                "type": "verbatim",

                                "timestamp_granularities": [
                                    "word"
                                ]
                            }
                        }
                    }
                )

                break

            except Exception as e:

                if attempt < 2:

                    time.sleep(8)

                else:

                    st.error(
                        "Gemini មានបញ្ហាពេលស្តាប់សំឡេង។"
                    )

                    st.code(
                        f"{type(e).__name__}: {str(e)}"
                    )

                    st.stop()


        # =================================================
        # Get words
        # =================================================

        words = get_word_annotations(
            interaction
        )

        if not words:

            st.error(
                "Gemini មិនបានផ្តល់ timestamp សម្រាប់ពាក្យទេ។"
            )

            try:

                st.code(
                    interaction.output_text
                )

            except Exception:
                pass

            st.stop()


        # =================================================
        # Create segments
        # =================================================

        segments = make_segments(
            words,
            max_words=8
        )

        if not segments:

            st.error(
                "រកមិនឃើញការនិយាយក្នុងវីដេអូ។"
            )

            st.stop()


        st.write(
            f"រកឃើញការនិយាយចំនួន {len(segments)} ផ្នែក"
        )


        # =================================================
        # 3. Translate Chinese → Khmer
        # =================================================

        st.write(
            "2️⃣ កំពុងបកប្រែជាខ្មែរ តាមផ្នែក..."
        )

        translated_segments = []


        for index, segment in enumerate(segments):

            chinese = segment["text"]

            khmer = ""


            translation_models = [
                "gemini-3.8-flash",
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-3.5-flash"
            ]


            for model_name in translation_models:

                for attempt in range(2):

                    try:

                        response = client.models.generate_content(

                            model=model_name,

                            contents=(
                                "Translate this spoken Chinese "
                                "into natural conversational Khmer. "
                                "Keep the meaning and emotion. "
                                "Keep the Khmer sentence short enough "
                                "to fit approximately the original "
                                "speaking time. "
                                "Return ONLY Khmer.\n\n"
                                f"{chinese}"
                            ),

                            config=types.GenerateContentConfig(
                                temperature=0.2
                            )
                        )

                        khmer = (
                            response.text or ""
                        ).strip()


                        if khmer:
                            break


                    except Exception as e:

                        if attempt == 0:

                            time.sleep(5)

                        else:

                            continue


                if khmer:
                    break


            if not khmer:

                st.error(
                    f"Gemini មិនអាចបកប្រែផ្នែកទី {index + 1} បានទេ។"
                )

                st.stop()


            translated_segments.append({

                "text": khmer,

                "start": segment["start"],

                "end": segment["end"]
            })


        # =================================================
        # 4. Generate Khmer AI voice
        # =================================================

        st.write(
            "3️⃣ កំពុងបង្កើតសំឡេង AI ខ្មែរ..."
        )

        segment_audio_files = []


        for index, segment in enumerate(
            translated_segments
        ):

            text = segment["text"]


            if len(text) > 1200:

                st.error(
                    f"ផ្នែកទី {index + 1} លើស 1200 តួអក្សរ។"
                )

                st.stop()


            try:

                r = requests.post(

                    "https://doslarb.cloud/api/v1/tts",

                    headers={
                        "Authorization":
                            f"Bearer {doslarb_key}",

                        "Content-Type":
                            "application/json"
                    },

                    json={
                        "text": text,
                        "voice": voice
                    },

                    timeout=120
                )

            except Exception as e:

                st.error(
                    "មិនអាចភ្ជាប់ Doslarb បានទេ។"
                )

                st.code(str(e))

                st.stop()


            if not r.ok:

                st.error(
                    f"Doslarb TTS error {r.status_code}"
                )

                st.code(
                    r.text
                )

                st.stop()


            segment_file = (
                td / f"segment_{index}.mp3"
            )

            segment_file.write_bytes(
                r.content
            )

            segment_audio_files.append(
                segment_file
            )


        # =================================================
        # 5. Get video duration
        # =================================================

        st.write(
            "4️⃣ កំពុងតម្រឹមសំឡេងខ្មែរតាមពេលនិយាយ..."
        )


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


        match = re.search(

            r"Duration:\s*(\d+):(\d+):([\d.]+)",

            probe.stderr
        )


        if not match:

            st.error(
                "មិនអាចរកប្រវែងវីដេអូបាន។"
            )

            st.code(
                probe.stderr[-2000:]
            )

            st.stop()


        hours = int(
            match.group(1)
        )

        minutes = int(
            match.group(2)
        )

        seconds = float(
            match.group(3)
        )


        video_duration = (
            hours * 3600
            + minutes * 60
            + seconds
        )


        # =================================================
        # 6. Delay each Khmer voice
        # =================================================

        delayed_tracks = []


        for index, segment in enumerate(
            translated_segments
        ):

            start_ms = int(
                segment["start"] * 1000
            )

            delayed = (
                td / f"delayed_{index}.wav"
            )


            try:

                subprocess.run(

                    [
                        ffmpeg,
                        "-y",

                        "-i",
                        str(
                            segment_audio_files[index]
                        ),

                        "-af",
                        f"adelay={start_ms}|{start_ms}",

                        "-ar",
                        "44100",

                        "-ac",
                        "2",

                        str(delayed)
                    ],

                    check=True,

                    stdout=subprocess.DEVNULL,

                    stderr=subprocess.PIPE
                )

            except Exception as e:

                st.error(
                    f"មិនអាចតម្រឹមសំឡេងផ្នែកទី {index + 1} បានទេ។"
                )

                st.code(str(e))

                st.stop()


            delayed_tracks.append(
                delayed
            )


        # =================================================
        # 7. Mix all voices
        # =================================================

        mixed_audio = (
            td / "khmer_final.wav"
        )


        inputs = []

        for track in delayed_tracks:

            inputs.extend([
                "-i",
                str(track)
            ])


        filter_parts = []

        for i in range(
            len(delayed_tracks)
        ):

            filter_parts.append(
                f"[{i}:a]"
            )


        filter_complex = (

            "".join(filter_parts)

            + f"amix=inputs="
            + str(len(delayed_tracks))
            + ":duration=longest:"
            + "dropout_transition=0,"
            + "volume=1"
        )


        try:

            subprocess.run(

                [
                    ffmpeg,
                    "-y",

                    *inputs,

                    "-filter_complex",
                    filter_complex,

                    "-t",
                    str(video_duration),

                    "-ar",
                    "44100",

                    "-ac",
                    "2",

                    str(mixed_audio)
                ],

                check=True,

                stdout=subprocess.DEVNULL,

                stderr=subprocess.PIPE
            )

        except Exception as e:

            st.error(
                "មិនអាចបញ្ចូលសំឡេងជាចម្រៀងតែមួយបានទេ។"
            )

            st.code(str(e))

            st.stop()


        # =================================================
        # 8. Put Khmer audio into video
        # =================================================

        st.write(
            "5️⃣ កំពុងបញ្ចូលសំឡេងខ្មែរទៅក្នុងវីដេអូ..."
        )


        try:

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

        except Exception as e:

            st.error(
                "មិនអាចបង្កើត MP4 ចុងក្រោយបានទេ។"
            )

            st.code(str(e))

            st.stop()


        # =================================================
        # Finished
        # =================================================

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
