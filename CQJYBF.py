import os
import subprocess
import numpy as np
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import concurrent.futures
from moviepy.editor import VideoFileClip, concatenate_videoclips
import threading
import queue
import math

def extract_audio_frames_ffmpeg(audio_clip, fps=44100):
    """使用ffmpeg直接从音频剪辑中提取音频帧"""
    command = [
        "ffmpeg",
        "-i", audio_clip.filename,
        "-acodec", "pcm_s16le",
        "-ar", str(fps),
        "-ac", "1",
        "-f", "s16le",
        "-"
    ]
    pipe = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = pipe.communicate()
    audio_frames = np.frombuffer(out, np.int16)
    return audio_frames

def analyze_audio(audio_clip, volume_percentage, frame_rate=44100, chunk_size=4410):
    """分析音频，返回音量低于阈值的时间段列表"""
    low_volume_segments = []
    audio_frames = extract_audio_frames_ffmpeg(audio_clip, fps=frame_rate)
    num_frames = len(audio_frames)
    
    # 计算最高音量
    max_volume = max(20 * np.log10(np.sqrt(np.mean(audio_frames[i:i+chunk_size]**2))) 
                     for i in range(0, num_frames, chunk_size))
    
    # 计算阈值（百分比）
    threshold_volume = max_volume * (volume_percentage / 10)

    for i in range(0, num_frames, chunk_size):
        chunk = audio_frames[i:i+chunk_size]
        volume = 20 * np.log10(np.sqrt(np.mean(chunk**2)))
        if volume < threshold_volume:
            start_time = i / frame_rate
            end_time = (i + chunk_size) / frame_rate
            low_volume_segments.append((start_time, end_time))
    return low_volume_segments

def extract_audio(video_path):
    """从视频中提取音频并返回音频对象"""
    video = VideoFileClip(video_path)
    return video.audio

def cut_video(video_path, segments_to_remove):
    """根据提供的时间段列表裁剪视频"""
    video = VideoFileClip(video_path)
    remaining_segments = []
    last_end = 0
    for start, end in segments_to_remove:
        if start > last_end:
            remaining_segments.append(video.subclip(last_end, start))
        last_end = end
    if last_end < video.duration:
        remaining_segments.append(video.subclip(last_end, video.duration))
    final_clip = concatenate_videoclips(remaining_segments)
    return final_clip

def analyze_and_process_video(file_path, output_folder, volume_percentage, progress_queue):
    try:
        audio_clip = extract_audio(file_path)
        low_volume_segments = analyze_audio(audio_clip, volume_percentage=volume_percentage)

        if not low_volume_segments:
            progress_queue.put(f"文件 {os.path.basename(file_path)} 音量正常，无需裁剪")
            return

        final_video = cut_video(file_path, low_volume_segments)
        output_path = os.path.join(output_folder, os.path.basename(file_path))
        final_video.write_videofile(output_path, codec="libx264")
        progress_queue.put(f"完成处理文件 {os.path.basename(file_path)}")
    except Exception as e:
        progress_queue.put(f"处理文件 {os.path.basename(file_path)} 时出错: {e}")


def analyze_and_process_video(file_path, output_folder, volume_percentage, progress_queue):
    try:
        audio_clip = extract_audio(file_path)
        low_volume_segments = analyze_audio(audio_clip, volume_percentage=volume_percentage)

        if not low_volume_segments:
            progress_queue.put(f"文件 {os.path.basename(file_path)} 音量正常，无需裁剪")
            return

        final_video = cut_video(file_path, low_volume_segments)
        output_path = os.path.join(output_folder, os.path.splitext(os.path.basename(file_path))[0] + '.mp4')

        # ffmpeg命令，使用libx264编码器，将输出文件格式指定为mp4
        ffmpeg_command = ['ffmpeg', '-y', '-i', file_path, '-c:v', 'libx264', output_path]
        process = subprocess.Popen(ffmpeg_command, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8', errors='ignore')
        for line in process.stderr:
            if 'frame=' in line:
                progress_queue.put(line)  # 将ffmpeg输出的行发送到队列

        final_video.write_videofile(output_path, codec='libx264')
        progress_queue.put(f'完成处理文件 {os.path.basename(file_path)}')
    except Exception as e:
        progress_queue.put(f'处理文件 {os.path.basename(file_path)} 时出错: {e}')
def batch_process_videos(folder_path, output_folder, volume_percentage, progress_queue):
    try:
        # 修改这里，以包括 .mp4 和 .mkv 文件
        files = [f for f in os.listdir(folder_path) if f.endswith(".mp4") or f.endswith(".mkv")]
        if not files:
            raise Exception("输入文件夹中没有找到MP4或MKV文件。")

        total_files = len(files)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            for file in files:
                file_path = os.path.join(folder_path, file)
                futures.append(executor.submit(analyze_and_process_video, file_path, output_folder, volume_percentage, progress_queue))

            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                progress_queue.put((i + 1) / total_files * 100)
                future.result()
    except Exception as e:
        progress_queue.put(f"批处理时出错: {e}")


def start_processing():
    input_folder = input_dir.get()
    output_folder = output_dir.get()
    volume_percentage = float(volume_threshold_entry.get())

    if not input_folder or not output_folder:
        messagebox.showerror("错误", "请输入文件夹路径")
        return

    progress_queue = queue.Queue()
    threading.Thread(target=batch_process_videos, args=(input_folder, output_folder, volume_percentage, progress_queue), daemon=True).start()

    app.after(100, update_progress, progress_queue)

def update_progress(progress_queue):
    try:
        while True:
            message = progress_queue.get_nowait()
            if isinstance(message, float):
                progress_bar['value'] = message
            elif "出错" in message:
                messagebox.showerror("处理错误", message)
            else:
                progress_label_var.set(message)
    except queue.Empty:
        pass

    app.after(100, update_progress, progress_queue)

def select_input_folder():
    directory = filedialog.askdirectory()
    input_dir.set(directory)

def select_output_folder():
    directory = filedialog.askdirectory()
    output_dir.set(directory)

# 创建图形界面
app = tk.Tk()
app.title("视频音量处理器")

input_dir = tk.StringVar()
output_dir = tk.StringVar()
progress_label_var = tk.StringVar()

# 输入文件夹选择
input_frame = tk.Frame(app)
input_frame.pack(padx=10, pady=5)
tk.Label(input_frame, text="选择输入文件夹：").pack(side=tk.LEFT)
tk.Entry(input_frame, textvariable=input_dir, width=50).pack(side=tk.LEFT)
tk.Button(input_frame, text="浏览", command=select_input_folder).pack(side=tk.LEFT)

# 输出文件夹选择
output_frame = tk.Frame(app)
output_frame.pack(padx=10, pady=5)
tk.Label(output_frame, text="选择输出文件夹：").pack(side=tk.LEFT)
tk.Entry(output_frame, textvariable=output_dir, width=50).pack(side=tk.LEFT)
tk.Button(output_frame, text="浏览", command=select_output_folder).pack(side=tk.LEFT)

# 音量阈值输入
volume_threshold_frame = tk.Frame(app)
volume_threshold_frame.pack(padx=10, pady=5)
tk.Label(volume_threshold_frame, text="音量阈值（0-10）：").pack(side=tk.LEFT)
volume_threshold_entry = tk.Entry(volume_threshold_frame)
volume_threshold_entry.pack(side=tk.LEFT)
volume_threshold_entry.insert(0, "4.0")

# 进度条和进度标签
progress_frame = tk.Frame(app)
progress_frame.pack(padx=10, pady=5)
progress_bar = ttk.Progressbar(progress_frame, orient='horizontal', length=400, mode='determinate')
progress_bar.pack(side=tk.LEFT)
progress_label = tk.Label(progress_frame, textvariable=progress_label_var)
progress_label.pack(side=tk.LEFT)

# 开始处理按钮
start_button = tk.Button(app, text="开始处理", command=start_processing)
start_button.pack(pady=20)

app.mainloop()
