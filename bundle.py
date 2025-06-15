import subprocess
import shutil
import os
import sys

def find_required_binaries():
    """
    Finds the full paths to ffmpeg.exe, ffprobe.exe, and yt-dlp.exe
    by looking them up in the system's PATH.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    yt_dlp_path = shutil.which("yt-dlp")

    missing_binaries = []
    if not ffmpeg_path:
        missing_binaries.append("ffmpeg.exe")
    if not ffprobe_path:
        missing_binaries.append("ffprobe.exe")
    if not yt_dlp_path:
        missing_binaries.append("yt-dlp.exe")

    if missing_binaries:
        print("Error: The following required executables were not found in your system's PATH:")
        for binary in missing_binaries:
            print(f"- {binary}")
        print("\nPlease ensure these tools are installed and their respective directories are added to your system's PATH environment variable before bundling.")
        sys.exit(1)
    
    print(f"Found ffmpeg.exe at: {ffmpeg_path}")
    print(f"Found ffprobe.exe at: {ffprobe_path}")
    print(f"Found yt-dlp.exe at: {yt_dlp_path}")
    
    return ffmpeg_path, ffprobe_path, yt_dlp_path

def create_executable():
    """
    Creates a standalone executable of main.py using PyInstaller,
    bundling ffmpeg.exe, ffprobe.exe, and yt-dlp.exe.
    """
    main_script = "main.py"
    executable_name = "SpotifyDownloader" # Name of your final .exe file

    if not os.path.exists(main_script):
        print(f"Error: '{main_script}' not found in the current directory.")
        sys.exit(1)

    # Find the paths to the binaries from the system's PATH
    ffmpeg_exe, ffprobe_exe, yt_dlp_exe = find_required_binaries()

    # PyInstaller command:
    # --noconsole: CRITICAL for GUI apps to prevent a console window from opening with the GUI.
    # --onefile: Creates a single executable file. (Consider --onedir for fewer false positives)
    # --name: Sets the name of the executable.
    # --add-binary: Adds external binaries. Format is "source;destination".
    #               "." means the root of the temporary extraction folder when the exe runs.
    # --clean: Cleans PyInstaller cache and temporary files before building.
    
    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        main_script,
        "--noconsole",
        "--onefile", # Recommended for a single file, but prone to AV false positives. Consider "--onedir"
        "--name", executable_name,
        "--add-binary", f"{os.path.normpath(ffmpeg_exe)};.",
        "--add-binary", f"{os.path.normpath(ffprobe_exe)};.",
        "--add-binary", f"{os.path.normpath(yt_dlp_exe)};.", # Explicitly add yt-dlp.exe
        "--clean"
        # Optional: Add an icon for your executable
        # "--icon", "path/to/your/icon.ico" 
    ]

    print("\nStarting PyInstaller build process...")
    print(f"Command: {' '.join(pyinstaller_cmd)}\n")

    try:
        # Run PyInstaller
        process = subprocess.run(pyinstaller_cmd, check=True, text=True, capture_output=True)
        print("PyInstaller Output (stdout):\n", process.stdout)
        if process.stderr:
            print("PyInstaller Output (stderr):\n", process.stderr)
        
        print("\nBuild complete!")
        dist_path = os.path.join("dist", f"{executable_name}{'.exe' if sys.platform == 'win32' else ''}")
        print(f"Executable created at: {os.path.abspath(dist_path)}")
        print("You can find your executable in the 'dist' folder.")

    except subprocess.CalledProcessError as e:
        print(f"\nError: PyInstaller failed with return code {e.returncode}")
        print("PyInstaller Output (stdout):\n", e.stdout)
        print("PyInstaller Output (stderr):\n", e.stderr)
        print("Please check the output above for details on the error.")
    except FileNotFoundError:
        print("\nError: PyInstaller command not found.")
        print("Please ensure PyInstaller is installed ('pip install pyinstaller').")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")

if __name__ == "__main__":
    create_executable()