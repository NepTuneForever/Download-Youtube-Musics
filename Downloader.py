from __future__ import annotations

import json
import queue
import re
import subprocess
import threading
import zipfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

try:
    import requests
except ModuleNotFoundError as exc:
    missing_package = exc.name or "requests"
    raise SystemExit(
        f"Dependencia ausente: {missing_package}\n"
        "Instale com: pip install -r requirements.txt"
    ) from exc

try:
    import yt_dlp
except ModuleNotFoundError as exc:
    missing_package = exc.name or "yt-dlp"
    raise SystemExit(
        f"Dependencia ausente: {missing_package}\n"
        "Instale com: pip install -r requirements.txt"
    ) from exc


BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "musicas baixadas"
FFMPEG_DIR = BASE_DIR / "ffmpeg"
FFMPEG_ZIP = BASE_DIR / "ffmpeg.zip"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
YOUTUBE_SEARCH_LIMIT = 15
INVALID_FILENAME_CHARS = r'<>:"/\\|?*'
SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(f"[{re.escape(INVALID_FILENAME_CHARS)}]", "", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.rstrip(". ") or "musica"


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "Duracao desconhecida"

    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def parse_duration_text(duration_text: str | None) -> int | None:
    if not duration_text:
        return None

    parts = duration_text.split(":")
    try:
        numbers = [int(part) for part in parts]
    except ValueError:
        return None

    total = 0
    for number in numbers:
        total = (total * 60) + number
    return total


def ensure_downloads_dir() -> Path:
    DOWNLOADS_DIR.mkdir(exist_ok=True)
    return DOWNLOADS_DIR


def find_local_ffmpeg_bin() -> Path | None:
    if not FFMPEG_DIR.exists():
        return None

    for candidate in FFMPEG_DIR.glob("**/bin"):
        ffmpeg_exe = candidate / "ffmpeg.exe"
        ffprobe_exe = candidate / "ffprobe.exe"
        if ffmpeg_exe.exists() and ffprobe_exe.exists():
            return candidate
    return None


def install_ffmpeg(status_callback: Callable[[str], None] | None = None) -> str:
    existing_bin = find_local_ffmpeg_bin()
    if existing_bin is not None:
        return str(existing_bin)

    if status_callback:
        status_callback("Baixando FFmpeg...")

    response = requests.get(FFMPEG_URL, stream=True, timeout=60)
    response.raise_for_status()
    with FFMPEG_ZIP.open("wb") as file_handle:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                file_handle.write(chunk)

    if status_callback:
        status_callback("Extraindo FFmpeg...")

    with zipfile.ZipFile(FFMPEG_ZIP, "r") as zip_ref:
        zip_ref.extractall(FFMPEG_DIR)

    FFMPEG_ZIP.unlink(missing_ok=True)

    ffmpeg_bin = find_local_ffmpeg_bin()
    if ffmpeg_bin is None:
        raise RuntimeError("Nao foi possivel localizar o FFmpeg extraido.")

    return str(ffmpeg_bin)


def extract_runs_text(node: dict[str, Any] | None) -> str:
    if not node:
        return ""
    if "simpleText" in node:
        return node.get("simpleText") or ""
    runs = node.get("runs") or []
    return "".join(run.get("text", "") for run in runs if isinstance(run, dict))


def walk_json_nodes(node: Any) -> Any:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_json_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_json_nodes(item)


def extract_yt_initial_data(html: str) -> dict[str, Any]:
    match = re.search(r"var ytInitialData = (\{.*?\});", html)
    if not match:
        raise RuntimeError("Nao foi possivel ler os resultados da pagina do YouTube.")
    return json.loads(match.group(1))


def search_youtube(term: str) -> list[dict[str, Any]]:
    query = term.strip()
    if not query:
        raise ValueError("Digite algo para pesquisar.")

    search_url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
    response = requests.get(search_url, headers=SEARCH_HEADERS, timeout=20)
    response.raise_for_status()

    data = extract_yt_initial_data(response.text)
    normalized_entries: list[dict[str, Any]] = []
    seen_video_ids: set[str] = set()

    for item in walk_json_nodes(data):
        video_renderer = item.get("videoRenderer") if isinstance(item, dict) else None
        if not video_renderer:
            continue

        video_id = video_renderer.get("videoId")
        if not video_id or video_id in seen_video_ids:
            continue

        title = extract_runs_text(video_renderer.get("title")) or "Sem titulo"
        uploader = (
            extract_runs_text(video_renderer.get("ownerText"))
            or extract_runs_text(video_renderer.get("longBylineText"))
            or "Canal desconhecido"
        )
        duration_text = extract_runs_text(video_renderer.get("lengthText"))
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        normalized_entries.append(
            {
                "title": title,
                "url": video_url,
                "webpage_url": video_url,
                "uploader": uploader,
                "duration": parse_duration_text(duration_text),
                "source_type": "search",
            }
        )
        seen_video_ids.add(video_id)

        if len(normalized_entries) >= YOUTUBE_SEARCH_LIMIT:
            break

    return normalized_entries


def fetch_video_info(source_url: str) -> dict[str, Any]:
    options = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(source_url, download=False)

    return {
        "title": info.get("title") or "musica",
        "url": info.get("webpage_url") or source_url,
        "webpage_url": info.get("webpage_url") or source_url,
        "uploader": info.get("uploader") or info.get("channel") or "Canal desconhecido",
        "duration": info.get("duration"),
        "source_type": "link",
    }


def make_unique_output_stem(title: str) -> Path:
    safe_title = sanitize_filename(title)
    candidate = ensure_downloads_dir() / safe_title
    suffix = 1

    while candidate.with_suffix(".mp3").exists() or any(candidate.parent.glob(f"{candidate.name}.*")):
        suffix += 1
        candidate = ensure_downloads_dir() / f"{safe_title} ({suffix})"
    return candidate


def download_audio(
    source_url: str,
    title: str,
    status_callback: Callable[[str], None] | None = None,
) -> Path:
    if not source_url:
        raise ValueError("Nenhum link para download foi informado.")

    if not title or title == "musica":
        if status_callback:
            status_callback("Buscando titulo do video...")
        title = fetch_video_info(source_url).get("title") or "musica"

    ffmpeg_location = install_ffmpeg(status_callback=status_callback)
    ffmpeg_bin_dir = Path(ffmpeg_location)
    ffmpeg_executable = ffmpeg_bin_dir / "ffmpeg.exe"
    last_error: Exception | None = None

    def progress_hook(progress: dict[str, Any]) -> None:
        if not status_callback:
            return
        status = progress.get("status")
        if status == "downloading":
            percent = progress.get("_percent_str", "").strip()
            speed = progress.get("_speed_str", "").strip()
            eta = progress.get("_eta_str", "").strip()
            parts = ["Baixando"]
            if percent:
                parts.append(percent)
            if speed:
                parts.append(speed)
            if eta:
                parts.append(f"ETA {eta}")
            status_callback(" | ".join(parts))
        elif status == "finished":
            status_callback("Convertendo para MP3...")

    attempts = [
        {
            "name": "tentativa principal",
            "format": "bestaudio/best",
            "player_clients": ["web", "android"],
            "use_postprocessor": True,
        },
        {
            "name": "fallback m4a/webm",
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
            "player_clients": ["android", "web_creator"],
            "use_postprocessor": True,
        },
        {
            "name": "fallback bruto + conversao manual",
            "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
            "player_clients": ["android", "ios", "web"],
            "use_postprocessor": False,
        },
    ]

    for attempt_index, attempt in enumerate(attempts, start=1):
        target_stem = make_unique_output_stem(title)
        target_mp3 = target_stem.with_suffix(".mp3")

        if status_callback:
            status_callback(f"Iniciando {attempt['name']} ({attempt_index}/{len(attempts)})...")

        ydl_opts = {
            "format": attempt["format"],
            "outtmpl": str(target_stem) + ".%(ext)s",
            "ffmpeg_location": ffmpeg_location,
            "noplaylist": True,
            "quiet": True,
            "progress_hooks": [progress_hook],
            "retries": 10,
            "fragment_retries": 10,
            "file_access_retries": 5,
            "extractor_retries": 5,
            "geo_bypass": True,
            "concurrent_fragment_downloads": 1,
            "extractor_args": {
                "youtube": {
                    "player_client": attempt["player_clients"],
                }
            },
        }

        if attempt["use_postprocessor"]:
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([source_url])

            if target_mp3.exists():
                return target_mp3

            if not attempt["use_postprocessor"]:
                source_candidates = sorted(target_stem.parent.glob(f"{target_stem.name}.*"))
                source_candidates = [candidate for candidate in source_candidates if candidate.suffix.lower() != ".mp3"]
                if not source_candidates:
                    raise RuntimeError("Nao foi encontrado arquivo de audio temporario para converter.")

                source_file = source_candidates[0]
                if status_callback:
                    status_callback("Convertendo fallback para MP3...")

                subprocess.run(
                    [
                        str(ffmpeg_executable),
                        "-y",
                        "-i",
                        str(source_file),
                        "-vn",
                        "-codec:a",
                        "libmp3lame",
                        "-b:a",
                        "192k",
                        str(target_mp3),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                source_file.unlink(missing_ok=True)

                if target_mp3.exists():
                    return target_mp3
                raise RuntimeError("A conversao fallback terminou, mas o MP3 nao foi encontrado.")

            raise RuntimeError("O download terminou, mas o arquivo MP3 nao foi encontrado.")
        except Exception as exc:
            last_error = exc
            for candidate in target_stem.parent.glob(f"{target_stem.name}.*"):
                candidate.unlink(missing_ok=True)
            if status_callback:
                status_callback(f"{attempt['name']} falhou. Tentando alternativa...")

    raise RuntimeError(f"Falha em todas as tentativas de download: {last_error}")


class MusicDownloaderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("YouTube Music Downloader")
        self.root.geometry("1100x760")
        self.root.minsize(980, 700)

        self.search_var = tk.StringVar()
        self.link_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Pronto.")
        self.search_selection_var = tk.StringVar(value="1")
        self.queue_selection_var = tk.StringVar(value="1")
        self.results: list[dict[str, Any]] = []
        self.download_queue: list[dict[str, Any]] = []
        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.is_busy = False
        self.retry_only_failures = False

        self.build_ui()
        self.render_results([])
        self.render_download_queue()
        self.root.after(150, self.process_event_queue)

    def build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        container = ttk.Frame(self.root, padding=16)
        container.grid(sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(2, weight=1)

        header = ttk.Label(
            container,
            text="Baixar musicas do YouTube",
            font=("Segoe UI", 18, "bold"),
        )
        header.grid(row=0, column=0, columnspan=2, sticky="w")

        search_frame = ttk.LabelFrame(container, text="Pesquisar musica", padding=12)
        search_frame.grid(row=1, column=0, sticky="ew", pady=(16, 12), padx=(0, 8))
        search_frame.columnconfigure(0, weight=1)

        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        search_entry.bind("<Return>", lambda _event: self.handle_search())

        self.search_button = ttk.Button(search_frame, text="Pesquisar", command=self.handle_search)
        self.search_button.grid(row=0, column=1)

        results_frame = ttk.LabelFrame(container, text="Resultados", padding=12)
        results_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 12), padx=(0, 8))
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

        self.results_text = scrolledtext.ScrolledText(
            results_frame,
            wrap="word",
            height=18,
            font=("Consolas", 10),
            state="disabled",
            cursor="arrow",
        )
        self.results_text.grid(row=0, column=0, sticky="nsew")
        self.results_text.bind("<Button-1>", self.handle_results_click)

        results_controls = ttk.Frame(results_frame)
        results_controls.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        results_controls.columnconfigure(4, weight=1)

        ttk.Label(results_controls, text="Selecionar resultado:").grid(row=0, column=0, sticky="w")
        self.search_selection_spinbox = tk.Spinbox(
            results_controls,
            from_=1,
            to=1,
            textvariable=self.search_selection_var,
            width=6,
            command=self.handle_search_selection_submit,
        )
        self.search_selection_spinbox.grid(row=0, column=1, padx=(8, 8), sticky="w")
        self.search_selection_spinbox.bind("<Return>", lambda _event: self.handle_search_selection_submit())

        self.select_result_button = ttk.Button(
            results_controls,
            text="Aplicar selecao",
            command=self.handle_search_selection_submit,
            state="disabled",
        )
        self.select_result_button.grid(row=0, column=2, sticky="w")

        self.add_to_queue_button = ttk.Button(
            results_controls,
            text="Adicionar a lista",
            command=self.handle_add_selected_result,
            state="disabled",
        )
        self.add_to_queue_button.grid(row=0, column=3, padx=(8, 0), sticky="w")

        self.result_details_label = ttk.Label(
            results_frame,
            text="Pesquise uma musica para ver resultados.",
            justify="left",
            wraplength=480,
        )
        self.result_details_label.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        queue_frame = ttk.LabelFrame(container, text="Lista de downloads", padding=12)
        queue_frame.grid(row=1, column=1, rowspan=2, sticky="nsew", pady=(16, 12))
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.rowconfigure(0, weight=1)

        self.queue_text = scrolledtext.ScrolledText(
            queue_frame,
            wrap="word",
            height=18,
            font=("Consolas", 10),
            state="disabled",
            cursor="arrow",
        )
        self.queue_text.grid(row=0, column=0, sticky="nsew")
        self.queue_text.bind("<Button-1>", self.handle_queue_click)

        queue_controls = ttk.Frame(queue_frame)
        queue_controls.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        queue_controls.columnconfigure(5, weight=1)

        ttk.Label(queue_controls, text="Selecionar item:").grid(row=0, column=0, sticky="w")
        self.queue_selection_spinbox = tk.Spinbox(
            queue_controls,
            from_=1,
            to=1,
            textvariable=self.queue_selection_var,
            width=6,
            command=self.handle_queue_selection_submit,
        )
        self.queue_selection_spinbox.grid(row=0, column=1, padx=(8, 8), sticky="w")
        self.queue_selection_spinbox.bind("<Return>", lambda _event: self.handle_queue_selection_submit())

        self.remove_from_queue_button = ttk.Button(
            queue_controls,
            text="Remover selecionada",
            command=self.handle_remove_queue_item,
            state="disabled",
        )
        self.remove_from_queue_button.grid(row=0, column=2, sticky="w")

        self.download_queue_button = ttk.Button(
            queue_controls,
            text="Baixar musicas da lista",
            command=self.handle_download_queue,
            state="disabled",
        )
        self.download_queue_button.grid(row=0, column=3, padx=(8, 0), sticky="w")

        self.retry_failed_button = ttk.Button(
            queue_controls,
            text="Tentar novamente falhas",
            command=self.handle_retry_failed_downloads,
            state="disabled",
        )
        self.retry_failed_button.grid(row=0, column=4, padx=(8, 0), sticky="w")

        self.queue_details_label = ttk.Label(
            queue_frame,
            text="Nenhuma musica na lista.",
            justify="left",
            wraplength=480,
        )
        self.queue_details_label.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        link_frame = ttk.LabelFrame(container, text="Adicionar por link", padding=12)
        link_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        link_frame.columnconfigure(0, weight=1)

        link_entry = ttk.Entry(link_frame, textvariable=self.link_var)
        link_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        link_entry.bind("<Return>", lambda _event: self.handle_add_link())

        self.add_link_button = ttk.Button(
            link_frame,
            text="Adicionar link a lista",
            command=self.handle_add_link,
        )
        self.add_link_button.grid(row=0, column=1)

        footer = ttk.Frame(container)
        footer.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)

        ttk.Label(
            footer,
            text=f"Destino: {DOWNLOADS_DIR}",
            wraplength=760,
            justify="left",
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            container,
            textvariable=self.status_var,
            relief="sunken",
            anchor="w",
            padding=(8, 6),
        ).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def set_busy(self, busy: bool) -> None:
        self.is_busy = busy
        state = "disabled" if busy else "normal"

        self.search_button.config(state=state)
        self.add_link_button.config(state=state)
        self.search_selection_spinbox.config(state=state)
        self.queue_selection_spinbox.config(state=state)

        if busy:
            self.select_result_button.config(state="disabled")
            self.add_to_queue_button.config(state="disabled")
            self.remove_from_queue_button.config(state="disabled")
            self.download_queue_button.config(state="disabled")
            self.retry_failed_button.config(state="disabled")
            return

        if self.get_selected_result() is not None:
            self.select_result_button.config(state="normal")
            self.add_to_queue_button.config(state="normal")
        else:
            self.select_result_button.config(state="disabled")
            self.add_to_queue_button.config(state="disabled")

        if self.get_selected_queue_item() is not None:
            self.remove_from_queue_button.config(state="normal")
        else:
            self.remove_from_queue_button.config(state="disabled")

        if self.download_queue:
            self.download_queue_button.config(state="normal")
        else:
            self.download_queue_button.config(state="disabled")

        if any(item.get("last_error") for item in self.download_queue):
            self.retry_failed_button.config(state="normal")
        else:
            self.retry_failed_button.config(state="disabled")

    def enqueue_event(self, name: str, payload: Any) -> None:
        self.event_queue.put((name, payload))

    def process_event_queue(self) -> None:
        try:
            while True:
                event, payload = self.event_queue.get_nowait()
                if event == "status":
                    self.set_status(payload)
                elif event == "search_results":
                    self.handle_search_results(payload)
                elif event == "search_error":
                    self.set_status(payload)
                    messagebox.showerror("Erro", payload)
                    self.set_busy(False)
                elif event == "metadata_success":
                    self.handle_link_metadata_success(payload)
                elif event == "metadata_error":
                    self.set_status(payload)
                    messagebox.showerror("Erro", payload)
                    self.set_busy(False)
                elif event == "queue_item_success":
                    self.handle_queue_item_success(payload)
                elif event == "queue_item_error":
                    self.handle_queue_item_error(payload)
                elif event == "queue_done":
                    self.handle_queue_done(payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self.process_event_queue)

    def set_text_widget_content(self, widget: scrolledtext.ScrolledText, content: str) -> None:
        widget.config(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        widget.config(state="disabled")

    def render_results(self, results: list[dict[str, Any]]) -> None:
        if not results:
            self.set_text_widget_content(self.results_text, "Nenhum resultado encontrado.")
            self.search_selection_var.set("1")
            self.search_selection_spinbox.config(from_=1, to=1)
            self.result_details_label.config(text="Nenhum resultado selecionado.")
            self.select_result_button.config(state="disabled")
            self.add_to_queue_button.config(state="disabled")
            return

        self.results_text.config(state="normal")
        self.results_text.delete("1.0", tk.END)
        self.results_text.tag_configure("result_item", spacing1=4, spacing3=8)
        self.results_text.tag_configure("result_title", font=("Consolas", 10, "bold"))

        for index, item in enumerate(results, start=1):
            start_index = self.results_text.index(tk.INSERT)
            self.results_text.insert(
                tk.END,
                f"{index}. {item.get('title') or 'Sem titulo'}\n",
                ("result_item", "result_title"),
            )
            self.results_text.insert(
                tk.END,
                f"   Canal: {item.get('uploader') or 'Canal desconhecido'}\n"
                f"   Duracao: {format_duration(item.get('duration'))}\n"
                f"   Link: {item.get('webpage_url') or item.get('url') or 'Nao disponivel'}\n\n",
                ("result_item",),
            )
            end_index = self.results_text.index(tk.INSERT)
            self.results_text.tag_add(f"result_{index - 1}", start_index, end_index)

        self.results_text.config(state="disabled")
        self.search_selection_var.set("1")
        self.search_selection_spinbox.config(from_=1, to=len(results))
        if not self.is_busy:
            self.select_result_button.config(state="normal")
            self.add_to_queue_button.config(state="normal")
        self.show_selected_result(0)

    def render_download_queue(self) -> None:
        if not self.download_queue:
            self.set_text_widget_content(self.queue_text, "Nenhuma musica na lista.")
            self.queue_selection_var.set("1")
            self.queue_selection_spinbox.config(from_=1, to=1)
            self.queue_details_label.config(text="Nenhuma musica na lista.")
            self.remove_from_queue_button.config(state="disabled")
            self.download_queue_button.config(state="disabled")
            return

        self.queue_text.config(state="normal")
        self.queue_text.delete("1.0", tk.END)
        self.queue_text.tag_configure("queue_item", spacing1=4, spacing3=8)
        self.queue_text.tag_configure("queue_title", font=("Consolas", 10, "bold"))

        for index, item in enumerate(self.download_queue, start=1):
            start_index = self.queue_text.index(tk.INSERT)
            self.queue_text.insert(
                tk.END,
                f"{index}. {item.get('title') or 'Sem titulo'}\n",
                ("queue_item", "queue_title"),
            )
            status_line = "   Status: pronto para baixar"
            if item.get("last_error"):
                status_line = f"   Status: falhou anteriormente - {item.get('last_error')}"
            self.queue_text.insert(
                tk.END,
                f"   Canal: {item.get('uploader') or 'Canal desconhecido'}\n"
                f"   Duracao: {format_duration(item.get('duration'))}\n"
                f"{status_line}\n"
                f"   Link: {item.get('webpage_url') or item.get('url') or 'Nao disponivel'}\n\n",
                ("queue_item",),
            )
            end_index = self.queue_text.index(tk.INSERT)
            self.queue_text.tag_add(f"queue_{index - 1}", start_index, end_index)

        self.queue_text.config(state="disabled")
        selected_index = self.get_selected_queue_index()
        if selected_index is None or selected_index >= len(self.download_queue):
            selected_index = 0
        self.queue_selection_var.set(str(selected_index + 1))
        self.queue_selection_spinbox.config(from_=1, to=len(self.download_queue))
        self.show_selected_queue_item(selected_index)

    def get_selected_result_index(self) -> int | None:
        try:
            index = int(self.search_selection_var.get()) - 1
        except ValueError:
            return None
        if index < 0 or index >= len(self.results):
            return None
        return index

    def get_selected_result(self) -> dict[str, Any] | None:
        index = self.get_selected_result_index()
        if index is None:
            return None
        return self.results[index]

    def get_selected_queue_index(self) -> int | None:
        try:
            index = int(self.queue_selection_var.get()) - 1
        except ValueError:
            return None
        if index < 0 or index >= len(self.download_queue):
            return None
        return index

    def get_selected_queue_item(self) -> dict[str, Any] | None:
        index = self.get_selected_queue_index()
        if index is None:
            return None
        return self.download_queue[index]

    def show_selected_result(self, index: int) -> None:
        if index < 0 or index >= len(self.results):
            self.result_details_label.config(text="Nenhum resultado selecionado.")
            return

        self.search_selection_var.set(str(index + 1))
        selected = self.results[index]
        details = [
            f"Titulo: {selected.get('title', 'Sem titulo')}",
            f"Canal: {selected.get('uploader') or 'Canal desconhecido'}",
            f"Duracao: {format_duration(selected.get('duration'))}",
            f"Link: {selected.get('webpage_url') or selected.get('url') or 'Nao disponivel'}",
        ]
        self.result_details_label.config(text="\n".join(details))
        if not self.is_busy:
            self.select_result_button.config(state="normal")
            self.add_to_queue_button.config(state="normal")

    def show_selected_queue_item(self, index: int) -> None:
        if index < 0 or index >= len(self.download_queue):
            self.queue_details_label.config(text="Nenhuma musica na lista.")
            return

        self.queue_selection_var.set(str(index + 1))
        selected = self.download_queue[index]
        details = [
            f"Titulo: {selected.get('title', 'Sem titulo')}",
            f"Canal: {selected.get('uploader') or 'Canal desconhecido'}",
            f"Duracao: {format_duration(selected.get('duration'))}",
            f"Status: {'falhou anteriormente' if selected.get('last_error') else 'pronto para baixar'}",
            f"Link: {selected.get('webpage_url') or selected.get('url') or 'Nao disponivel'}",
        ]
        if selected.get("last_error"):
            details.append(f"Ultimo erro: {selected.get('last_error')}")
        self.queue_details_label.config(text="\n".join(details))
        if not self.is_busy:
            self.remove_from_queue_button.config(state="normal")

    def get_tagged_index_from_text(self, widget: scrolledtext.ScrolledText, prefix: str, event: Any) -> int | None:
        text_index = widget.index(f"@{event.x},{event.y}")
        for tag in widget.tag_names(text_index):
            if tag.startswith(prefix):
                try:
                    return int(tag.split("_", 1)[1])
                except ValueError:
                    return None
        return None

    def handle_results_click(self, event: Any) -> str:
        result_index = self.get_tagged_index_from_text(self.results_text, "result_", event)
        if result_index is not None:
            self.show_selected_result(result_index)
        return "break"

    def handle_queue_click(self, event: Any) -> str:
        queue_index = self.get_tagged_index_from_text(self.queue_text, "queue_", event)
        if queue_index is not None:
            self.show_selected_queue_item(queue_index)
        return "break"

    def handle_search_selection_submit(self) -> None:
        index = self.get_selected_result_index()
        if index is None:
            messagebox.showwarning("Selecao invalida", "Escolha um numero de resultado valido.")
            return
        self.show_selected_result(index)

    def handle_queue_selection_submit(self) -> None:
        index = self.get_selected_queue_index()
        if index is None:
            messagebox.showwarning("Selecao invalida", "Escolha um numero de item valido da lista.")
            return
        self.show_selected_queue_item(index)

    def handle_search(self) -> None:
        term = self.search_var.get().strip()
        if not term:
            messagebox.showwarning("Campo vazio", "Digite o nome de uma musica para pesquisar.")
            return
        if self.is_busy:
            return

        self.set_busy(True)
        self.set_status("Pesquisando no YouTube...")
        self.set_text_widget_content(self.results_text, "Pesquisando... aguarde.")
        self.result_details_label.config(text="Aguardando retorno da busca.")
        self.search_selection_var.set("1")
        self.search_selection_spinbox.config(from_=1, to=1)
        self.select_result_button.config(state="disabled")
        self.add_to_queue_button.config(state="disabled")

        threading.Thread(target=self.run_search, args=(term,), daemon=True).start()

    def run_search(self, term: str) -> None:
        try:
            results = search_youtube(term)
            self.enqueue_event("search_results", results)
        except Exception as exc:
            self.enqueue_event("search_error", f"Falha ao pesquisar: {exc}")

    def handle_search_results(self, results: list[dict[str, Any]]) -> None:
        self.results = results
        self.render_results(results)
        self.set_status(f"{len(results)} resultado(s) encontrado(s).")
        self.set_busy(False)

    def handle_add_selected_result(self) -> None:
        selected = self.get_selected_result()
        if selected is None:
            messagebox.showwarning("Sem selecao", "Escolha uma musica da busca para adicionar.")
            return
        if self.is_busy:
            return

        self.download_queue.append(dict(selected))
        self.download_queue[-1]["last_error"] = None
        self.render_download_queue()
        self.queue_selection_var.set(str(len(self.download_queue)))
        self.show_selected_queue_item(len(self.download_queue) - 1)
        self.set_status(f"Adicionada a lista: {selected.get('title') or 'musica'}")

    def handle_add_link(self) -> None:
        link = self.link_var.get().strip()
        if not link:
            messagebox.showwarning("Campo vazio", "Cole um link do YouTube para adicionar.")
            return
        if self.is_busy:
            return

        self.set_busy(True)
        self.set_status("Lendo dados do link...")
        threading.Thread(target=self.run_fetch_link_metadata, args=(link,), daemon=True).start()

    def run_fetch_link_metadata(self, source_url: str) -> None:
        try:
            info = fetch_video_info(source_url)
            self.enqueue_event("metadata_success", info)
        except Exception as exc:
            self.enqueue_event("metadata_error", f"Falha ao ler o link: {exc}")

    def handle_link_metadata_success(self, info: dict[str, Any]) -> None:
        self.download_queue.append(info)
        self.download_queue[-1]["last_error"] = None
        self.link_var.set("")
        self.render_download_queue()
        self.queue_selection_var.set(str(len(self.download_queue)))
        self.show_selected_queue_item(len(self.download_queue) - 1)
        self.set_status(f"Adicionada a lista: {info.get('title') or 'musica'}")
        self.set_busy(False)

    def handle_remove_queue_item(self) -> None:
        index = self.get_selected_queue_index()
        if index is None:
            messagebox.showwarning("Sem selecao", "Escolha uma musica da lista para remover.")
            return
        if self.is_busy:
            return

        removed = self.download_queue.pop(index)
        self.render_download_queue()
        self.set_status(f"Removida da lista: {removed.get('title') or 'musica'}")

    def handle_download_queue(self) -> None:
        if not self.download_queue:
            messagebox.showwarning("Lista vazia", "Adicione musicas a lista antes de baixar.")
            return
        if self.is_busy:
            return

        queue_snapshot = [dict(item) for item in self.download_queue]
        self.retry_only_failures = False
        self.set_busy(True)
        self.set_status(f"Iniciando fila com {len(queue_snapshot)} musica(s)...")
        threading.Thread(target=self.run_download_queue, args=(queue_snapshot,), daemon=True).start()

    def handle_retry_failed_downloads(self) -> None:
        failed_items = [dict(item) for item in self.download_queue if item.get("last_error")]
        if not failed_items:
            messagebox.showwarning("Sem falhas", "Nao ha musicas com falha para tentar novamente.")
            return
        if self.is_busy:
            return

        self.retry_only_failures = True
        self.set_busy(True)
        self.set_status(f"Tentando novamente {len(failed_items)} musica(s) com falha...")
        threading.Thread(target=self.run_download_queue, args=(failed_items,), daemon=True).start()

    def run_download_queue(self, items: list[dict[str, Any]]) -> None:
        success_count = 0
        failure_count = 0

        for index, item in enumerate(items, start=1):
            title = item.get("title") or "musica"
            source_url = item.get("webpage_url") or item.get("url")
            self.enqueue_event("status", f"Baixando {index}/{len(items)}: {title}")
            try:
                output_path = download_audio(source_url, title, status_callback=lambda message: self.enqueue_event("status", message))
                success_count += 1
                self.enqueue_event(
                    "queue_item_success",
                    {
                        "source_url": source_url,
                        "title": title,
                        "output_path": str(output_path),
                    },
                )
            except Exception as exc:
                failure_count += 1
                self.enqueue_event(
                    "queue_item_error",
                    {
                        "source_url": source_url,
                        "title": title,
                        "error": str(exc),
                    },
                )

        self.enqueue_event(
            "queue_done",
            {
                "success_count": success_count,
                "failure_count": failure_count,
            },
        )

    def handle_queue_item_success(self, payload: dict[str, Any]) -> None:
        source_url = payload.get("source_url")
        for index, item in enumerate(self.download_queue):
            item_url = item.get("webpage_url") or item.get("url")
            if item_url == source_url:
                self.download_queue.pop(index)
                break

        self.render_download_queue()
        self.set_status(f"Baixada e removida da lista: {payload.get('title') or 'musica'}")

    def handle_queue_item_error(self, payload: dict[str, Any]) -> None:
        title = payload.get("title") or "musica"
        error = payload.get("error") or "Erro desconhecido"
        source_url = payload.get("source_url")
        for item in self.download_queue:
            item_url = item.get("webpage_url") or item.get("url")
            if item_url == source_url:
                item["last_error"] = error
                break
        self.render_download_queue()
        self.set_status(f"Falha em '{title}': {error}")

    def handle_queue_done(self, payload: dict[str, Any]) -> None:
        success_count = payload.get("success_count", 0)
        failure_count = payload.get("failure_count", 0)
        if self.retry_only_failures:
            summary = f"Tentativa das falhas concluida. Baixadas: {success_count}. Falhas restantes: {failure_count}."
        else:
            summary = f"Todas as musicas da lista foram processadas. Baixadas: {success_count}. Falhas: {failure_count}."
        self.set_busy(False)
        self.set_status(summary)
        self.retry_only_failures = False
        messagebox.showinfo("Fila finalizada", summary)


def main() -> None:
    ensure_downloads_dir()
    root = tk.Tk()
    app = MusicDownloaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
