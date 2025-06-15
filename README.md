# Spotify Downloader
A downloader for Spotify using YT-Dlp and FFmpeg.

This is a downloader for spotify meant to be combinded with
https://github.com/THEBEST7192/spotify-tierlist

To get the JSON file use the [Spotify Tierlist](https://github.com/THEBEST7192/spotify-tierlist) website

To play songs use VLC player or [Spotify Player](https://github.com/THEBEST7192/spotify-player) (Coming soon)

## Requirements
- FFmpeg
- yt-dlp

## Installation
1. Download FFmpeg from https://ffmpeg.org/download.html
2. Download yt-dlp from https://github.com/yt-dlp/yt-dlp/releases

3. Add FFmpeg and yt-dlp to the path
If you need help, you can look [here](https://www.wikihow.com/Install-FFmpeg-on-Windows)

## Usage (Python)
This requires yt-dlp and FFmpeg on path
1. Run the script:
```bash
python main.py
```
2. Select a JSON file containing Spotify track URIs
3. Click "Download Tracks"

Or 
## (Usage executable)
You may have problems because of some AVs not liking Pyinstaller bundled projects, so you may have to set up an exception for it, this does not require anything on path
1. Open SpotifyDownloader.exe
2. Select a JSON file containing Spotify track URIs
3. Click "Download Tracks"


## Bundling/building the project
1. Install pyinstaller
```bash
pip install pyinstaller
```

2. To bundle the project you need to run
```bash
python bundle.py
```
This assumes that both FFmpeg and yt-dlp are on your path,
the exe file will be in the dist folder.

## Troubleshooting
If you see any errors it is most likely because of a shitty code, send me a message on Discord (@thebest7192) or make a issue