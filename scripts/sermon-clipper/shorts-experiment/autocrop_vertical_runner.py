"""Run AutoCrop-Vertical's scene/content logic with a short-clip-safe fallback."""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path


class _SimpleTimecode:
    def __init__(self, frames: int, fps: float) -> None:
        self._frames = max(0, int(frames))
        self._fps = max(1.0, float(fps or 30.0))

    def get_frames(self) -> int:
        return self._frames

    def get_seconds(self) -> float:
        return float(self._frames) / float(self._fps)

    def get_timecode(self) -> str:
        total = self.get_seconds()
        hh = int(total // 3600)
        mm = int((total % 3600) // 60)
        ss = total % 60.0
        return f"{hh:02d}:{mm:02d}:{ss:06.3f}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Short-clip-safe AutoCrop-Vertical runner.")
    parser.add_argument("--repo-dir", required=True, help="Checkout directory for AutoCrop-Vertical.")
    parser.add_argument("-i", "--input", required=True, help="Input video path.")
    parser.add_argument("-o", "--output", required=True, help="Output video path.")
    parser.add_argument("--ratio", default="9:16", help="Output aspect ratio, default 9:16.")
    parser.add_argument("--quality", default="balanced", choices=["fast", "balanced", "high"])
    return parser.parse_args()


def _load_upstream(repo_dir: Path):
    main_py = repo_dir / "main.py"
    if not main_py.exists():
        raise RuntimeError(f"AutoCrop-Vertical not found at {main_py}")
    spec = importlib.util.spec_from_file_location("autocrop_vertical_upstream", main_py)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load AutoCrop-Vertical from {main_py}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_ratio(raw: str) -> float:
    parts = str(raw or "9:16").split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid ratio: {raw}")
    width = int(parts[0])
    height = int(parts[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid ratio: {raw}")
    return float(width) / float(height)


def _mux_audio(input_video: Path, temp_video: Path, output_video: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(temp_video),
        "-i",
        str(input_video),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-shortest",
        str(output_video),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main() -> None:
    args = _parse_args()
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    repo_dir = Path(args.repo_dir).resolve()
    input_video = Path(args.input).resolve()
    output_video = Path(args.output).resolve()
    upstream = _load_upstream(repo_dir)
    upstream.ASPECT_RATIO = _parse_ratio(args.ratio)

    import cv2  # type: ignore
    import numpy as np  # type: ignore
    from tqdm import tqdm  # type: ignore

    try:
        upstream.get_yolo_model().to("cpu")
    except Exception:
        pass

    original_width, original_height, fps = upstream.get_video_properties(str(input_video))
    output_height = original_height if original_height % 2 == 0 else original_height + 1
    output_width = int(output_height * upstream.ASPECT_RATIO)
    if output_width % 2 != 0:
        output_width += 1

    cap = cv2.VideoCapture(str(input_video))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open input video {input_video}")
    total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    cap.release()

    scenes, _scene_fps = upstream.detect_scenes(str(input_video))
    if not scenes:
        scenes = [(_SimpleTimecode(0, fps), _SimpleTimecode(total_frames, fps))]

    scenes_analysis: list[dict] = []
    for start_time, end_time in scenes:
        analysis = upstream.analyze_scene_content(str(input_video), start_time, end_time)
        strategy, target_box = upstream.decide_cropping_strategy(analysis, original_height)
        scenes_analysis.append(
            {
                "start_frame": start_time.get_frames(),
                "end_frame": end_time.get_frames(),
                "strategy": strategy,
                "target_box": target_box,
            }
        )

    encoder_args = upstream.build_encoder_args("libx264", str(args.quality))
    with tempfile.TemporaryDirectory(prefix="autocrop-vertical-") as tmp_dir_raw:
        tmp_dir = Path(tmp_dir_raw)
        temp_video_output = tmp_dir / "vertical-video.mp4"
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-s",
            f"{output_width}x{output_height}",
            "-pix_fmt",
            "bgr24",
            "-r",
            str(fps),
            "-i",
            "-",
            "-c:v",
            "libx264",
            *encoder_args,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-vsync",
            "cfr",
            "-an",
            str(temp_video_output),
        ]
        ffmpeg_process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        cap = cv2.VideoCapture(str(input_video))
        frame_number = 0
        current_scene_index = 0
        last_output_frame = None

        with tqdm(total=total_frames, desc="AutoCrop-Vertical", unit="fr", dynamic_ncols=True) as pbar:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                if current_scene_index < len(scenes_analysis) - 1 and frame_number >= scenes_analysis[current_scene_index + 1]["start_frame"]:
                    current_scene_index += 1

                scene_data = scenes_analysis[current_scene_index]
                strategy = scene_data["strategy"]
                target_box = scene_data["target_box"]
                try:
                    if strategy == "TRACK" and target_box:
                        crop_box = upstream.calculate_crop_box(target_box, original_width, original_height)
                        processed_frame = frame[crop_box[1] : crop_box[3], crop_box[0] : crop_box[2]]
                        output_frame = cv2.resize(processed_frame, (output_width, output_height))
                    else:
                        scale_factor = output_width / original_width
                        scaled_height = int(original_height * scale_factor)
                        scaled_frame = cv2.resize(frame, (output_width, scaled_height))
                        output_frame = np.zeros((output_height, output_width, 3), dtype=np.uint8)
                        y_offset = max(0, (output_height - scaled_height) // 2)
                        output_frame[y_offset : y_offset + scaled_height, :] = scaled_frame
                    last_output_frame = output_frame
                except Exception:
                    if last_output_frame is not None:
                        output_frame = last_output_frame
                    else:
                        output_frame = np.zeros((output_height, output_width, 3), dtype=np.uint8)

                if ffmpeg_process.stdin is None:
                    raise RuntimeError("ffmpeg stdin closed unexpectedly")
                ffmpeg_process.stdin.write(output_frame.tobytes())
                frame_number += 1
                pbar.update(1)

        cap.release()
        if ffmpeg_process.stdin is not None:
            ffmpeg_process.stdin.close()
        stderr_output = (ffmpeg_process.stderr.read() if ffmpeg_process.stderr else b"").decode("utf-8", errors="replace")
        ffmpeg_process.wait()
        if ffmpeg_process.returncode != 0:
            raise RuntimeError(f"ffmpeg encode failed: {stderr_output[-1200:]}")

        output_video.parent.mkdir(parents=True, exist_ok=True)
        if upstream.has_audio_stream(str(input_video)):
            _mux_audio(input_video, temp_video_output, output_video)
        else:
            if output_video.exists():
                output_video.unlink()
            os.replace(temp_video_output, output_video)


if __name__ == "__main__":
    main()
