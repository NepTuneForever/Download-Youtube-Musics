import os
import yt_dlp
import requests
import zipfile

def install_ffmpeg():
    ffmpeg_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    ffmpeg_zip = "ffmpeg.zip"
    extract_folder = "ffmpeg"

    if not os.path.exists(extract_folder):
        print(" Baixando FFmpeg...")
        r = requests.get(ffmpeg_url, stream=True)
        with open(ffmpeg_zip, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

        print("Extraindo FFmpeg...")
        with zipfile.ZipFile(ffmpeg_zip, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)

        os.remove(ffmpeg_zip)
    
    ffmpeg_path = os.path.join(extract_folder, "ffmpeg-6.0-essentials_build", "bin")
    os.environ["PATH"] += os.pathsep + ffmpeg_path
    return ffmpeg_path

ffmpeg_path = install_ffmpeg()

y = input(str('Digite o nome da musica (tudo junto): '))
result = y + '.mp3'

ydl_opts = {
    'format': 'bestaudio/best',
    'outtmpl': result,
    'ffmpeg_location': ffmpeg_path,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}

x = input('Digite o link do video/musica que voce quer baixar: ')
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.download([x])
