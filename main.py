import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox
import json, subprocess, threading
import shutil
import os
import sys
import concurrent.futures
import re

# We'll no longer directly use 'import ffmpeg' for probing, 
# as we're doing manual subprocess calls for better control.
# However, we still need 'Path' for file system operations.
try:
    from pathlib import Path
except ImportError:
    Path = None
    # If Path is not available, we can fall back to os.path functions,
    # but it's generally a standard library.

class SpotifyJSONDownloader:
    def __init__(self, master):
        self.master = master
        master.title("Spotify JSON Downloader (using yt-dlp)")

        self.filepath = None
        self.download_dir = None
        btn_frame = tk.Frame(master)
        btn_frame.pack(padx=10, pady=10)

        self.select_btn = tk.Button(btn_frame, text="Select JSON File", command=self.select_file)
        self.select_btn.pack(side=tk.LEFT, padx=5)

        self.download_btn = tk.Button(btn_frame, text="Download Tracks", command=self.start_download)
        self.download_btn.pack(side=tk.LEFT, padx=5)

        self.log_area = scrolledtext.ScrolledText(master, width=80, height=20, state='disabled')
        self.log_area.pack(padx=10, pady=(0,10))

        self.ffprobe_exe_path = None 
        self.ffmpeg_exe_path = None # Also store ffmpeg.exe path for good measure, though yt-dlp uses it directly

    def select_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
        if path:
            self.filepath = path
            self.master.after(0, lambda: messagebox.showinfo("File Selected", f"Selected file:\n{path}"))

    def start_download(self):
        if not self.filepath:
            self.master.after(0, lambda: messagebox.showerror("Error", "Please select a JSON file first."))
            return
        
        # --- Determine paths for bundled executables (yt-dlp, ffmpeg, ffprobe) ---
        if getattr(sys, 'frozen', False): # Running as a PyInstaller bundle
            # sys._MEIPASS points to the temp extraction folder
            base_temp_path = sys._MEIPASS
            self.ffprobe_exe_path = os.path.join(base_temp_path, "ffprobe.exe")
            self.ffmpeg_exe_path = os.path.join(base_temp_path, "ffmpeg.exe")
            yt_dlp_executable = "yt-dlp.exe" # Assume yt-dlp is also bundled
            # If yt-dlp is not bundled, it needs to be in PATH or explicitly added via --add-binary
            # For now, we'll assume it's either in PATH or bundled as yt-dlp.exe
            # If it's bundled, its path is also in base_temp_path
            self.yt_dlp_path = os.path.join(base_temp_path, yt_dlp_executable)
            if not os.path.exists(self.yt_dlp_path):
                 # Fallback: if yt-dlp.exe isn't found in _MEIPASS, check system PATH
                 self.yt_dlp_path = shutil.which("yt-dlp")
                 if not self.yt_dlp_path:
                    self.master.after(0, lambda: messagebox.showerror("yt-dlp Missing", "yt-dlp.exe not found. Please ensure it's bundled or in your system PATH."))
                    return

        else: # Not bundled (running directly from Python)
            self.yt_dlp_path = shutil.which("yt-dlp")
            if not self.yt_dlp_path and shutil.which(sys.executable + " -m yt_dlp"):
                self.yt_dlp_path = sys.executable + " -m yt_dlp" # For pip installed module
            if not self.yt_dlp_path:
                self.master.after(0, lambda: messagebox.showerror("yt-dlp Missing", "yt-dlp not found in system PATH. Please install it."))
                return
            
            self.ffprobe_exe_path = shutil.which("ffprobe")
            self.ffmpeg_exe_path = shutil.which("ffmpeg")

        if not self.ffprobe_exe_path:
            self.master.after(0, lambda: messagebox.showerror("FFprobe Missing", "ffprobe.exe not found. Please ensure FFmpeg is installed and its 'bin' directory is added to your system's PATH, or correctly bundled."))
            return
        if not self.ffmpeg_exe_path:
            self.master.after(0, lambda: messagebox.showerror("FFmpeg Missing", "ffmpeg.exe not found. Please ensure FFmpeg is installed and its 'bin' directory is added to your system's PATH, or correctly bundled."))
            return

        self.log(f"Using yt-dlp from: {self.yt_dlp_path}\n")
        self.log(f"Using ffprobe from: {self.ffprobe_exe_path}\n")

        json_filename_base = os.path.basename(self.filepath).rsplit('.', 1)[0]
        
        base_parent_dir = "SpotifyDownloads_YTDLP"
        os.makedirs(base_parent_dir, exist_ok=True)

        playlist_folder_name = json_filename_base
        download_dir = os.path.join(base_parent_dir, playlist_folder_name)
        
        i = 1
        original_download_dir = download_dir
        while os.path.exists(download_dir):
            download_dir = f"{original_download_dir}_{i}"
            i += 1
        
        os.makedirs(download_dir, exist_ok=True)
        self.download_dir = download_dir

        self.master.after(0, lambda: self.select_btn.config(state='disabled'))
        self.master.after(0, lambda: self.download_btn.config(state='disabled'))
        threading.Thread(target=self.download).start()

    def _sanitize_filename(self, filename):
        """Removes invalid characters for Windows filenames."""
        # Define characters that are invalid in Windows filenames
        invalid_chars = r'[<>:"/\|?*\n\r\t]' # Added common newline/tab chars as well
        # Replace invalid characters with an underscore
        sanitized_filename = re.sub(invalid_chars, '_', filename)
        # Windows doesn't allow filenames to end with a dot or space
        sanitized_filename = sanitized_filename.rstrip(' .')
        return sanitized_filename

    def _download_single_song(self, track_info):
        track_name, artist_names, download_path = track_info
        
        if artist_names:
            artists_str = ", ".join(artist_names)
            search_query = f"ytsearch:{artists_str} - {track_name}"
            log_display_artists = artists_str
        else:
            artists_str = ""
            search_query = f"ytsearch:{track_name}"
            log_display_artists = "No Artist"

        self.log(f"[Downloading] {log_display_artists} - {track_name}\n")
        
        # yt-dlp's template will handle filename sanitization mostly
        # We ensure the base dir is sanitized
        safe_download_path = self._sanitize_filename(download_path)

        # Use yt-dlp's conditional output template for filename without 'NA'
        # The output template ensures the artist is only included if available, and hyphen is conditional.
        output_template = os.path.join(safe_download_path, "%(artist|)s%(artist& - |)s%(title)s.%(ext)s")
        
        cmd = [self.yt_dlp_path, "-x", "--audio-format", "mp3", 
               "--embed-thumbnail", "--embed-metadata",
               "-o", output_template, 
               search_query]

        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
        try:
            result = subprocess.run(cmd, 
                                    capture_output=True, 
                                    text=True,           
                                    encoding='utf-8', 
                                    errors='replace', 
                                    check=False,
                                    stdin=subprocess.DEVNULL, 
                                    startupinfo=startupinfo 
                                   )
            self.log(result.stdout)
            if result.stderr:
                self.log(f"STDERR for {track_name}:\n{result.stderr}\n")

            if result.returncode != 0:
                self.log(f"WARNING: yt-dlp failed to download '{track_name}' (Return code: {result.returncode})\n")
            else:
                self.log(f"SUCCESS: Finished '{track_name}'\n")

        except FileNotFoundError:
            self.log(f"ERROR: 'yt-dlp' executable not found at '{self.yt_dlp_path}'. Ensure it's correctly bundled/accessible.\n")
        except Exception as e:
            self.log(f"ERROR downloading '{track_name}': {e}\n")


    def download(self):
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            tracks_info_for_download = []
            for tier_key in data.get('state', {}):
                for item in data['state'][tier_key]:
                    content = item.get('content', {})
                    track_name = content.get('name')
                    
                    artist_names = []
                    artists_data = content.get('artists', [])
                    for artist in artists_data:
                        if artist.get('name', '').strip():
                            artist_names.append(artist['name'])
                    
                    if track_name:
                        tracks_info_for_download.append((track_name, artist_names, self.download_dir))
                    else:
                        self.log(f"Skipping item due to missing track name: {item}\n")
            
            if not tracks_info_for_download:
                self.master.after(0, lambda: messagebox.showwarning("No Tracks", "No valid track names found in JSON for yt-dlp download."))
                return

            self.log(f"Downloading to playlist folder: {self.download_dir}\n")

            MAX_CONCURRENT_DOWNLOADS = 5 
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
                futures = [executor.submit(self._download_single_song, track_info) for track_info in tracks_info_for_download]
                for future in concurrent.futures.as_completed(futures):
                    pass

            self.log("All downloads attempted.\n")
            
            # --- REVISED: Manual FFprobe Probing ---
            if Path is not None and self.ffprobe_exe_path and os.path.exists(self.ffprobe_exe_path):
                self.log("Probing downloaded files...\n")
                
                ffprobe_startupinfo = None
                if sys.platform == "win32":
                    ffprobe_startupinfo = subprocess.STARTUPINFO()
                    ffprobe_startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    ffprobe_startupinfo.wShowWindow = subprocess.SW_HIDE

                for fpath in Path(self.download_dir).glob("*.mp3"):
                    # Construct ffprobe command to output JSON
                    ffprobe_cmd = [
                        self.ffprobe_exe_path,
                        "-v", "quiet",           # Suppress verbose output
                        "-print_format", "json", # Output in JSON format
                        "-show_format",          # Show format info
                        "-show_streams",         # Show stream info
                        str(fpath)               # Input file path
                    ]
                    
                    try:
                        # Execute ffprobe directly using subprocess.run
                        ffprobe_result = subprocess.run(
                            ffprobe_cmd,
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace',
                            check=False, # Don't raise an exception for non-zero exit codes
                            stdin=subprocess.DEVNULL,
                            startupinfo=ffprobe_startupinfo
                        )

                        # Parse JSON output
                        if ffprobe_result.returncode == 0 and ffprobe_result.stdout:
                            try:
                                info = json.loads(ffprobe_result.stdout)
                                duration = info.get('format', {}).get('duration')
                                if duration:
                                    self.log(f"Probed {fpath.name}: duration={float(duration):.2f}s\n")
                                else:
                                    self.log(f"Probed {fpath.name}: duration not found.\n")
                            except json.JSONDecodeError:
                                self.log(f"ERROR: Failed to parse ffprobe JSON for {fpath.name}. STDOUT:\n{ffprobe_result.stdout[:500]}...\n")
                                self.log(f"FFprobe STDERR:\n{ffprobe_result.stderr}\n") # Log ffprobe stderr directly
                        else:
                            self.log(f"WARNING: ffprobe failed for {fpath.name} (Return code: {ffprobe_result.returncode}).\n")
                            self.log(f"FFprobe STDERR:\n{ffprobe_result.stderr}\n") # Log ffprobe stderr directly

                    except FileNotFoundError:
                        self.log(f"ERROR: ffprobe.exe not found at '{self.ffprobe_exe_path}' during probing.\n")
                    except Exception as e:
                        self.log(f"ERROR during ffprobe for {fpath.name}: {e}\n")
            else:
                self.log("Skipping file probing: ffprobe.exe path not found or not bundled.\n")

            self.master.after(0, lambda: messagebox.showinfo("Done", "All tracks have been processed by yt-dlp."))

        except json.JSONDecodeError:
            err_msg = "Error: Invalid JSON file. Please ensure the file is correctly formatted."
            self.log(f"{err_msg}\n")
            self.master.after(0, lambda msg=err_msg: messagebox.showerror("JSON Error", msg))
        except Exception as e:
            err_msg = str(e)
            self.log(f"An unexpected error occurred: {err_msg}\n")
            self.master.after(0, lambda msg=err_msg: messagebox.showerror("Error", msg))
        finally:
            self.master.after(0, lambda: self.select_btn.config(state='normal'))
            self.master.after(0, lambda: self.download_btn.config(state='normal'))

    def log(self, message):
        self.master.after(0, self._append_log, message)

    def _append_log(self, message):
        self.log_area.config(state='normal')
        self.log_area.insert(tk.END, message)
        self.log_area.see(tk.END)
        self.log_area.config(state='disabled')

if __name__ == '__main__':
    root = tk.Tk()
    app = SpotifyJSONDownloader(root)
    root.mainloop()