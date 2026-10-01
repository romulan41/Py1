import sounddevice as sd
import numpy as np
import whisper
import torch
import queue
import threading
import time
import sys

SAMPLE_RATE = 16000
BLOCK_DURATION = 5
DEVICE_NAME = "CABLE Output"

model = whisper.load_model("base")

audio_queue = queue.Queue()
stop_event = threading.Event()

def find_vb_cable_device():
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        if DEVICE_NAME.lower() in dev['name'].lower() and dev['max_input_channels'] > 0:
            return i
    return None

def audio_callback(indata, frames, time_info, status):
    if status:
        print(f"Audio status: {status}", file=sys.stderr)
    audio_queue.put(indata.copy())

def record_audio(device_id):
    with sd.InputStream(
        device=device_id,
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='float32',
        blocksize=int(SAMPLE_RATE * BLOCK_DURATION),
        callback=audio_callback
    ):
        while not stop_event.is_set():
            time.sleep(0.1)

def transcribe_loop():
    buffer = np.zeros((0,), dtype=np.float32)
    while not stop_event.is_set():
        try:
            chunk = audio_queue.get(timeout=0.5)
            buffer = np.concatenate([buffer, chunk.flatten()])
            
            if len(buffer) >= SAMPLE_RATE * BLOCK_DURATION:
                audio_segment = buffer[:SAMPLE_RATE * BLOCK_DURATION]
                buffer = buffer[SAMPLE_RATE * BLOCK_DURATION:]
                
                audio_segment = whisper.pad_or_trim(audio_segment)
                mel = whisper.log_mel_spectrogram(audio_segment).to(model.device)
                
                options = whisper.DecodingOptions(language="ro", fp16=torch.cuda.is_available())
                result = whisper.decode(model, mel, options)
                
                if result.text.strip():
                    print(f"[RO] {result.text.strip()}")
                    
        except queue.Empty:
            continue
        except Exception as e:
            print(f"Transcription error: {e}", file=sys.stderr)

def main():
    device_id = find_vb_cable_device()
    if device_id is None:
        print(f"VB-Cable device '{DEVICE_NAME}' not found!")
        print("Available input devices:")
        for i, dev in enumerate(sd.query_devices()):
            if dev['max_input_channels'] > 0:
                print(f"  [{i}] {dev['name']}")
        return

    print(f"Using device [{device_id}]: {sd.query_devices(device_id)['name']}")
    print("Starting Romanian subtitles... Press Ctrl+C to stop\n")

    recorder = threading.Thread(target=record_audio, args=(device_id,), daemon=True)
    transcriber = threading.Thread(target=transcribe_loop, daemon=True)
    
    recorder.start()
    transcriber.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        stop_event.set()
        recorder.join(timeout=2)
        transcriber.join(timeout=2)

if __name__ == "__main__":
    main()