import tkinter as tk
import re
from tkinter import filedialog, scrolledtext, messagebox
import json, subprocess, threading, datetime
import shutil
import os
import sys
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed

# Global flag to indicate if we should stop
global_stop = False

def signal_handler(sig, frame):
    global global_stop
    print("\nFinishing current download before exiting...")
    global_stop = True

try:
    from pathlib import Path
except ImportError:
    Path = None
    # If Path is not available, fall back to os.path functions
class AskPlaylistExistsDialog(tk.Toplevel):
    def __init__(self, parent, playlist_name, num_files, existing_folders=None):
        super().__init__(parent)
        self.transient(parent)
        self.title("Playlist Exists")
        self.result = "cancel"  # Default to cancel
        self.selected_folder = None

        message = f"The folder for '{playlist_name}' already exists and contains {num_files} files."
        tk.Label(self, text=message, wraplength=350).pack(padx=20, pady=10)
        tk.Label(self, text="Select an existing folder or create a new one:").pack(pady=5)

        self.folder_var = tk.StringVar()
        self.folder_var.set(None)  # Ensure no folder is selected by default
        folder_frame = tk.Frame(self)
        folder_frame.pack(pady=5)

        if existing_folders:
            existing_folders = sorted(existing_folders)
            for folder in existing_folders:
                tk.Radiobutton(folder_frame, text=folder, variable=self.folder_var, value=folder).pack(anchor='w')

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Use Selected Folder", command=self.on_update).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(btn_frame, text="Create New Folder", command=self.on_create_new).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(btn_frame, text="Cancel", command=self.on_cancel).pack(side=tk.LEFT, padx=5, pady=5)

        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        
        # Center the dialog
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
        self.wait_window(self)

    def on_create_new(self):
        self.result = "new"
        self.selected_folder = None
        self.destroy()

    def on_update(self):
        self.result = "update"
        self.selected_folder = self.folder_var.get()
        self.destroy()

    def on_cancel(self):
        self.result = "cancel"
        self.selected_folder = None
        self.destroy()

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
        self.log_lock = threading.Lock()
        self.max_workers = 5  # Number of concurrent downloads

        # Scan for incomplete downloads and missing log entries on startup
        self.master.after(500, self.check_for_incomplete_downloads)

    def check_for_incomplete_downloads(self):
        if not self.download_dir:
            return
        log_filepath = os.path.join(self.download_dir, 'download_log.json')
        downloaded_ids = set()
        if os.path.exists(log_filepath):
            try:
                with open(log_filepath, 'r', encoding='utf-8') as f_log:
                    log_data = json.load(f_log)
                    downloaded_ids = {item['track_id'] for item in log_data if 'track_id' in item}
            except Exception:
                pass
        # Find .part and .ytdl files
        orphaned_files = []
        for fname in os.listdir(self.download_dir):
            if fname.endswith('.part') or fname.endswith('.ytdl'):
                orphaned_files.append(fname)
        # Find audio files not in log
        audio_exts = ['.mp3', '.m4a', '.wav', '.ogg', '.flac']
        orphaned_tracks = []
        for fname in os.listdir(self.download_dir):
            if any(fname.endswith(ext) for ext in audio_exts):
                name = os.path.splitext(fname)[0]
                # crude check: name not in log
                if not any(name in entry.get('track_name', '') for entry in log_data):
                    orphaned_tracks.append(fname)
        if orphaned_files or orphaned_tracks:
            msg = "Some incomplete or unlogged downloads were found:\n"
            if orphaned_files:
                msg += "\nPartial files (likely interrupted):\n" + '\n'.join(orphaned_files)
            if orphaned_tracks:
                msg += "\nAudio files not in log (may be incomplete or added manually):\n" + '\n'.join(orphaned_tracks)
            msg += "\n\nWould you like to attempt to re-download these tracks?"
            if messagebox.askyesno("Incomplete Downloads Detected", msg):
                self.redownload_orphaned_tracks(orphaned_files, orphaned_tracks)

    def redownload_orphaned_tracks(self, orphaned_files, orphaned_tracks):
        # Remove orphaned .part/.ytdl files
        for fname in orphaned_files:
            try:
                os.remove(os.path.join(self.download_dir, fname))
            except Exception:
                pass
        # Attempt to re-download orphaned tracks (by name)
        for fname in orphaned_tracks:
            track_name = os.path.splitext(fname)[0]
            # Try to find in JSON file
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            found = False
            for tier in data.get('state', {}).values():
                for item in tier:
                    content = item.get('content', {})
                    if content.get('name') == track_name:
                        artist_names = [artist['name'].strip() for artist in content.get('artists', []) if isinstance(artist, dict) and artist.get('name', '').strip()]
                        self._download_track((track_name, artist_names, self.download_dir, item.get('id'), track_name))
                        found = True
                        break
                if found:
                    break
        messagebox.showinfo("Redownload Complete", "Redownload of orphaned tracks is complete.")

    def _sanitize_filename(self, name):
        """Remove characters that are invalid for file/folder names."""
        # Windows invalid chars: < > : " / \ | ? *
        # Also remove other potentially problematic chars.
        return re.sub(r'[<>:"/\\|?*]', '_', name).strip()

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

        if not self.filepath:
            self.master.after(0, lambda: messagebox.showerror("Error", "JSON file path is not set. Please select a JSON file."))
            return

        json_filename_base = os.path.basename(self.filepath).rsplit('.', 1)[0]
        
        music_dir = os.path.expanduser("~/Music")
        fallback_dir = os.path.expanduser("~/SpotifyDownloader")
        playlist_folder_name = self._sanitize_filename(json_filename_base)

        try:
            download_dir = os.path.join(music_dir, playlist_folder_name)
            os.makedirs(download_dir, exist_ok=True)
        except OSError:
            self.log("Could not create directory in Music folder. Falling back to SpotifyDownloader in user directory.")
            download_dir = os.path.join(fallback_dir, playlist_folder_name)
            self.master.after(0, lambda: messagebox.showwarning("Directory Fallback", "Could not create directory in Music folder. Falling back to SpotifyDownloader in user directory."))
            os.makedirs(download_dir, exist_ok=True)
        
        # Gather all existing folders that match the playlist_folder_name pattern
        parent_dir = os.path.dirname(download_dir)
        base_name = os.path.basename(download_dir)
        existing_folders = []
        if os.path.exists(parent_dir):
            for name in os.listdir(parent_dir):
                full_path = os.path.join(parent_dir, name)
                if os.path.isdir(full_path) and (name == base_name or name.startswith(base_name + "_")):
                    existing_folders.append(name)
        
        # If only one existing folder and it is empty, skip dialog and use it directly
        if len(existing_folders) == 1:
            only_folder = os.path.join(parent_dir, existing_folders[0])
            try:
                num_files = len([name for name in os.listdir(only_folder) if os.path.isfile(os.path.join(only_folder, name))])
            except OSError:
                num_files = 0
            if num_files == 0:
                download_dir = only_folder
                os.makedirs(download_dir, exist_ok=True)
                self.download_dir = download_dir
                self.master.after(0, lambda: self.select_btn.config(state='disabled'))
                self.master.after(0, lambda: self.download_btn.config(state='disabled'))
                threading.Thread(target=self.download).start()
                return
        
        if os.path.exists(download_dir):
            try:
                num_files = len([name for name in os.listdir(download_dir) if os.path.isfile(os.path.join(download_dir, name))])
            except OSError:
                num_files = 0

            dialog = AskPlaylistExistsDialog(self.master, playlist_folder_name, num_files, existing_folders=existing_folders)
            choice = dialog.result
            selected_folder = dialog.selected_folder

            if choice == "new":
                i = 1
                original_download_dir = download_dir
                while os.path.exists(download_dir):
                    download_dir = f"{original_download_dir}_{i}"
                    i += 1
                os.makedirs(download_dir)
            elif choice == "update" and selected_folder:
                download_dir = os.path.join(parent_dir, selected_folder)
            else: # "cancel" or window closed
                self.log("Download cancelled by user.\n")
                self.master.after(0, lambda: self.select_btn.config(state='normal'))
                self.master.after(0, lambda: self.download_btn.config(state='normal'))
                return
        else:
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

    def _download_track(self, track_info):
        track_name, artist_names, download_path, track_id, _ = track_info
        
        # Create a search query from artist and track name
        base_query = f"{' '.join(artist_names)} - {track_name}" if artist_names else track_name
        search_query = f"ytsearch1:{base_query}"
        self.log(f"Searching for: {search_query}\n")
        
        safe_download_path = shlex.quote(download_path) if sys.platform != 'win32' else download_path
        output_template = os.path.join(safe_download_path, f"{self._sanitize_filename(track_name)} - {self._sanitize_filename(', '.join(artist_names))}.%(ext)s")
        
        cmd = [self.yt_dlp_path, 
               "-x",  # Extract audio
               "--audio-format", "mp3",
               "--embed-thumbnail",
               "--embed-metadata",
               "--default-search", "ytsearch",  # Enable YouTube search
               "--format", "bestaudio/best",  # Get best audio quality
               "--audio-quality", "0",  # Best audio quality
               "--no-playlist",  # Don't download playlists
               "-o", output_template,
               search_query]  # The search query

        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', startupinfo=startupinfo)
            stdout, stderr = process.communicate()

            if process.returncode == 0:
                self.log(f"Successfully downloaded: {track_name}\n")
                
                # Check if we should stop
                if global_stop:
                    self.log("Finishing current download before shutdown...\n")
                    return

                # --- Log successful download ---
                log_filepath = os.path.join(download_path, 'download_log.json')
                new_entry = {
                    'track_id': track_id,
                    'track_name': track_name,
                    'artists': artist_names,
                    'search_query': search_query,
                    'downloaded_at': datetime.datetime.now().isoformat()
                }

                with self.log_lock:
                    log_data = []
                    if os.path.exists(log_filepath):
                        try:
                            with open(log_filepath, 'r', encoding='utf-8') as f:
                                log_data = json.load(f)
                        except (json.JSONDecodeError, FileNotFoundError):
                            pass # Overwrite if corrupt or missing
                    
                    if isinstance(log_data, list):
                        log_data.append(new_entry)
                    else: # If log is not a list, start a new one
                        log_data = [new_entry]

                    with open(log_filepath, 'w', encoding='utf-8') as f:
                        json.dump(log_data, f, indent=4)
                
            else:
                self.log(f"Error downloading {track_name}. yt-dlp stderr:\n{stderr}\n")

        except Exception as e:
            self.log(f"Exception while downloading {track_name}: {e}\n")

    def download(self):
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # --- Load download log ---
            log_filepath = os.path.join(self.download_dir, 'download_log.json')
            downloaded_tracks = set()
            if os.path.exists(log_filepath):
                try:
                    with open(log_filepath, 'r', encoding='utf-8') as f_log:
                        log_data = json.load(f_log)
                        # Use track_id as the unique identifier
                        downloaded_tracks = {item['track_id'] for item in log_data if 'track_id' in item}
                    self.log(f"Loaded {len(downloaded_tracks)} entries from download log.\n")
                except (json.JSONDecodeError, FileNotFoundError):
                    self.log(f"Warning: Could not parse {os.path.basename(log_filepath)}. Starting fresh for this folder.\n")

            tracks_info_for_download = []
            
            if not isinstance(data.get('state'), dict):
                self.log("Error: 'state' key not found or is not a dictionary in the JSON file.\n")
                self.master.after(0, lambda: messagebox.showerror("Invalid JSON", "The JSON file doesn't have the expected 'state' structure."))
                return
            
            total_tracks_in_json = 0
            # Process tracks from the 'state' dictionary
            for tier_name, tier_items in data['state'].items():
                if not isinstance(tier_items, list):
                    continue
                
                for item in tier_items:
                    total_tracks_in_json += 1
                    if not isinstance(item, dict):
                        continue
                    
                    content = item.get('content', {})
                    if not isinstance(content, dict):
                        self.log(f"Skipping item with invalid content: {item}\n")
                        continue
                    
                    track_id = item.get('id')
                    track_name = content.get('name')
                    
                    if not track_id or not track_name:
                        self.log(f"Skipping item with missing ID or name: {content.get('name', 'Unknown')}\n")
                        continue

                    # Use track_id as the unique identifier
                    if track_id in downloaded_tracks:
                        continue
                    
                    track_name = content.get('name')
                    if not track_name or not isinstance(track_name, str):
                        continue
                    
                    artist_names = [artist['name'].strip() for artist in content.get('artists', []) if isinstance(artist, dict) and artist.get('name', '').strip()]
                    
                    tracks_info_for_download.append((track_name, artist_names, self.download_dir, track_id, track_name))
            
            self.log(f"Found {total_tracks_in_json} tracks in JSON file.\n")
            if downloaded_tracks:
                self.log(f"{len(downloaded_tracks)} tracks were already downloaded.\n")

            if not tracks_info_for_download:
                self.log("No new tracks to download.\n")
                self.master.after(0, lambda: messagebox.showinfo("All Done", "No new tracks to download."))
                return
            
            self.log(f"Starting download of {len(tracks_info_for_download)} new tracks...\n")

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = [executor.submit(self._download_track, track_info) for track_info in tracks_info_for_download]
                
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        self.log(f"Error in download thread: {e}\n")

            self.log("All downloads completed or failed.\n")

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
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)  # Handle Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Handle termination
    
    root = tk.Tk()
    app = SpotifyJSONDownloader(root)
    
    def on_closing():
        global global_stop
        global_stop = True
        # Let the current download finish
        root.after(100, root.destroy)
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()