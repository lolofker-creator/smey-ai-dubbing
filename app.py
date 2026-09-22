import json
import re
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
st.caption(
    "វីដេអូចិន → ស្តាប់សំឡេង → បកប្រែខ្មែរ → "
    "សំឡេងខ្មែរ → MP4"
)


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
# Get media duration
# =========================================================

def get_duration(ffmpeg, file_path):

    result = subprocess.run(
        [
            ffmpeg,
            "-i",
            str(file_path)
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    match = re.search(
        r"Duration:\s*(\d+):(\d+):([\d.]+)",
        result.stderr
    )

    if not match:
        return 0.0

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))

    return (
        hours * 3600
        + minutes * 60
        + seconds
    )


# =========================================================
# Convert timestamp safely
# =========================================================

def parse_time(value):

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()

    if not text:
        return 0.0

    # Seconds
    try:
        return float(text)
    except Exception:
        pass

    # MM:SS
    parts = text.split(":")

    try:
        if len(parts) == 2:
            return (
                float(parts[0]) * 60
                + float(parts[1])
            )

        if len(parts) == 3:
            return (
                float(parts[0]) * 3600
                + float(parts[1]) * 60
                + float(parts[2])
            )

    except Exception:
        pass

    return 0.0


# =========================================================
# Make atempo filter
# =========================================================

def make_atempo_filter(speed):

    filters = []

    while speed < 0.5:
        filters.append("atempo=0.5")
        speed /= 0.5

    while speed > 2.0:
        filters.append("atempo=2.0")
        speed /= 2.0

    filters.append(f"atempo={speed:.6f}")

    return ",".join(filters)


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
            "សូមដាក់ GEMINI_API_KEY និង DOSLARB_API_KEY "
            "ក្នុង Streamlit Secrets"
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


        video_duration = get_duration(
            ffmpeg,
            video
        )

        if video_duration <= 0:

            st.error(
                "មិនអាចរកប្រវែងវីដេអូបានទេ។"
            )

            st.stop()


        # =================================================
        # Gemini
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
        # 2. Gemini 3.8 Flash transcription + timestamps
        # =================================================

        st.write(
            "🎧 Gemini កំពុងស្តាប់ និងរកពេលនិយាយ..."
        )


        schema = {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start": {
                                "type": "number"
                            },
                            "end": {
                                "type": "number"
                            },
                            "text": {
                                "type": "string"
                            }
                        },
                        "required": [
                            "start",
                            "end",
                            "text"
                        ]
                    }
                }
            },
            "required": [
                "segments"
            ]
        }


        transcript = None


        for attempt in range(3):

            try:

                response = client.models.generate_content(

                    model="gemini-3.8-flash",

                    contents=[
                        (
                            "Listen carefully to this Chinese audio. "
                            "Create a transcript divided into speaking "
                            "segments. For every segment provide:\n"
                            "1. start = exact approximate start time "
                            "in seconds\n"
                            "2. end = exact approximate end time "
                            "in seconds\n"
                            "3. text = only the spoken Chinese words\n\n"
                            "Do not translate.\n"
                            "Do not invent speech.\n"
                            "Do not include silence.\n"
                            "Keep segments short, normally 2 to 8 "
                            "spoken words.\n"
                            "Times must be between 0 and the audio "
                            "duration."
                        ),
                        audio_file
                    ],

                    config=types.GenerateContentConfig(

                        temperature=0.1,

                        response_mime_type="application/json",

                        response_schema=schema
                    )
                )


                raw = (
                    response.text or ""
                ).strip()


                if not raw:
                    raise ValueError(
                        "Gemini returned empty response"
                    )


                transcript = json.loads(
                    raw
                )

                break


            except Exception as e:

                if attempt < 2:

                    time.sleep(8)

                else:

                    st.error(
                        "Gemini មិនអាចស្តាប់សំឡេងបាន។"
                    )

                    st.code(
                        f"{type(e).__name__}: {str(e)}"
                    )

                    st.stop()


        # =================================================
        # Check segments
        # =================================================

        segments = (
            transcript.get(
                "segments",
                []
            )
        )


        clean_segments = []


        for item in segments:

            try:

                text = str(
                    item.get(
                        "text",
                        ""
                    )
                ).strip()

                start = parse_time(
                    item.get(
                        "start",
                        0
                    )
                )

                end = parse_time(
                    item.get(
                        "end",
                        0
                    )
                )


                if not text:
                    continue

                if end <= start:
                    continue

                if start < 0:
                    start = 0

                if end > video_duration:
                    end = video_duration

                if end <= start:
                    continue


                clean_segments.append({
                    "text": text,
                    "start": start,
                    "end": end
                })


            except Exception:
                continue


        if not clean_segments:

            st.error(
                "Gemini មិនបានរកឃើញផ្នែកនិយាយទេ។"
            )

            st.stop()


        st.success(
            f"រកឃើញការនិយាយ {len(clean_segments)} ផ្នែក"
        )


        # =================================================
        # 3. Translate each segment
        # =================================================

        st.write(
            "2️⃣ កំពុងបកប្រែជាខ្មែរ..."
        )


        translated_segments = []


        for index, segment in enumerate(
            clean_segments
        ):

            chinese = segment["text"]

            khmer = ""


            models = [
                "gemini-3.8-flash",
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-3.5-flash"
            ]


            for model_name in models:

                for attempt in range(2):

                    try:

                        response = client.models.generate_content(

                            model=model_name,

                            contents=(
                                "Translate this spoken Chinese "
                                "into natural conversational Khmer.\n\n"
                                "Keep the same meaning and emotion.\n"
                                "Keep the Khmer wording concise so "
                                "it can fit the original speaking "
                                "duration.\n"
                                "Return ONLY Khmer text.\n\n"
                                f"Chinese:\n{chinese}"
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


                    except Exception:

                        if attempt == 0:
                            time.sleep(5)


                if khmer:
                    break


            if not khmer:

                st.error(
                    f"មិនអាចបកប្រែផ្នែកទី "
                    f"{index + 1} បានទេ។"
                )

                st.stop()


            translated_segments.append({

                "text": khmer,

                "start": segment["start"],

                "end": segment["end"]
            })


        # =================================================
        # 4. Doslarb Khmer voice
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
                    f"ផ្នែកទី {index + 1} "
                    "លើស 1200 តួអក្សរ។"
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
                    f"Doslarb TTS error "
                    f"{r.status_code}"
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
        # 5. Fit each Khmer voice to original timing
        # =================================================

        st.write(
            "4️⃣ កំពុងតម្រឹមសំឡេងខ្មែរតាមពេលនិយាយ..."
        )


        delayed_tracks = []


        for index, segment in enumerate(
            translated_segments
        ):

            start = segment["start"]
            end = segment["end"]

            target_duration = max(
                end - start,
                0.2
            )


            original_audio = (
                segment_audio_files[index]
            )


            # Get generated voice duration

            generated_duration = get_duration(
                ffmpeg,
                original_audio
            )


            if generated_duration <= 0:

                st.error(
                    f"មិនអាចរកប្រវែងសំឡេង "
                    f"ផ្នែកទី {index + 1} បានទេ។"
                )

                st.stop()


            # If Khmer is longer than original timing,
            # speed it up so it fits.

            speed = (
                generated_duration
                / target_duration
            )


            if speed > 1.02:

                atempo_filter = make_atempo_filter(
                    speed
                )

            else:

                atempo_filter = "anull"


            start_ms = int(
                start * 1000
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
                        str(original_audio),

                        "-af",
                        (
                            f"{atempo_filter},"
                            f"adelay={start_ms}|{start_ms}"
                        ),

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
                    f"មិនអាចតម្រឹមសំឡេង "
                    f"ផ្នែកទី {index + 1} បានទេ។"
                )

                st.code(str(e))

                st.stop()


            delayed_tracks.append(
                delayed
            )


        # =================================================
        # 6. Mix all voices
        # =================================================

        st.write(
            "5️⃣ កំពុងបញ្ចូលសំឡេងទាំងអស់..."
        )


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
                "មិនអាចបញ្ចូលសំឡេងបានទេ។"
            )

            st.code(
                str(e)
            )

            st.stop()


        # =================================================
        # 7. Replace original audio
        # =================================================

        st.write(
            "6️⃣ កំពុងបង្កើតវីដេអូ MP4..."
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
            
        # =================================================
        # Finished
        # =================================================

        st.success(
            "🎉 រួចរាល់! សំឡេងខ្មែរត្រូវបានតម្រឹមតាមពេលនិយាយ។"
        )

        st.video(
            output.read_bytes()
        )

        st.download_button(
            "⬇️ ទាញយក MP4",
            output.read_bytes(),
            "smey_ai_dubbing.mp4",
            "video/mp4",
            use_container_width=True
        )

      
