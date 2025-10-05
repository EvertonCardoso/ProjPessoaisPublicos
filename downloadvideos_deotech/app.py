import os
import re
import time
import uuid
import json
import shutil
import threading
import subprocess
import datetime as dt
from pathlib import Path
from flask import Flask, render_template, request, send_file, abort, Response, jsonify
from werkzeug.utils import secure_filename

# fuso horário (se disponível no Python)
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None

# Flask com static explícito
app = Flask(__name__, static_folder="static", static_url_path="/static")

BASE_DIR = os.getcwd()
DOWNLOAD_DIR = Path(BASE_DIR) / "downloads"
COOKIES_DIR = Path(BASE_DIR) / "cookies"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
COOKIES_DIR.mkdir(parents=True, exist_ok=True)

# Padrões suportados (TikTok, YouTube, Instagram, Facebook)
SUPPORTED_PATTERNS = {
    "tiktok": re.compile(r"^(https?://)?(www\.)?(vm\.tiktok\.com|vt\.tiktok\.com|m?\.tiktok\.com)/", re.IGNORECASE),
    "youtube": re.compile(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE),
    "instagram": re.compile(r"^(https?://)?(www\.)?instagram\.com/", re.IGNORECASE),
    "facebook": re.compile(r"^(https?://)?(www\.)?(facebook\.com|fb\.watch)/", re.IGNORECASE),
}

def detect_platform(url: str) -> str | None:
    u = (url or "").strip()
    for name, rx in SUPPORTED_PATTERNS.items():
        if rx.match(u):
            return name
    return None

# ===== Infra de Jobs p/ progresso =====
JOBS = {}  # job_id -> {"queue": list[str], "done": bool, "file": Path|None, "error": str|None}
JOBS_LOCK = threading.Lock()

def job_put(job_id: str, payload: dict):
    with JOBS_LOCK:
        JOBS[job_id]["queue"].append(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")

def job_sse_stream(job_id: str):
    # Mantém conexão aberta enquanto houver mensagens ou até concluir
    while True:
        with JOBS_LOCK:
            msgs = JOBS.get(job_id, {}).get("queue", [])
            done = JOBS.get(job_id, {}).get("done", False)
        # envia tudo que tiver na fila
        while msgs:
            with JOBS_LOCK:
                chunk = JOBS[job_id]["queue"].pop(0)
            yield chunk
        if done:
            break
        time.sleep(0.15)

def build_cmd(platform: str, url: str, user_agent: str, output_template: str):
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--restrict-filenames",
        "--merge-output-format", "mp4",
        "--add-header", f"User-Agent: {user_agent}",
        "--geo-bypass",
        "--newline",                               # progresso linha-a-linha
        "-o", output_template,
        "--print", "after_move:filepath",
        "--print", "id",
    ]
    if platform == "tiktok":
        cmd += [
            "--extractor-args", "tiktok:hd=1",
            "-f", "bv*+ba/best/bestvideo+bestaudio/best",
            "--add-header", "Referer: https://www.tiktok.com/",
        ]
    elif platform == "youtube":
        cmd += [
            "-f", "bv*+ba/bestvideo+bestaudio/best",
            "--add-header", "Referer: https://www.youtube.com/",
        ]
    elif platform == "instagram":
        cmd += [
            "-f", "bv*+ba/best/bestvideo+bestaudio/best",
            "--add-header", "Referer: https://www.instagram.com/",
        ]
    elif platform == "facebook":
        cmd += [
            "-f", "bv*+ba/best/bestvideo+bestaudio/best",
            "--add-header", "Referer: https://www.facebook.com/",
        ]
    cmd.append(url)
    return cmd

def run_download(job_id: str, cmd: list[str]):
    # Snapshot do diretório para fallback
    before = {p: p.stat().st_mtime for p in DOWNLOAD_DIR.glob("*")}

    # Regex de progresso (tolerante a ETA/velocidade ausentes)
    rgx = re.compile(
        r"\[download\]\s+(\d+(?:\.\d+)?)%.*?of\s+([0-9.]+[KMG]?i?B)(?:.*?at\s+([0-9.]+[KMG]?i?B/s))?(?:.*?ETA\s+([0-9:]+))?",
        re.IGNORECASE
    )

    try:
        proc = subprocess.Popen(
            cmd, cwd=str(DOWNLOAD_DIR),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        final_path_str = ""
        vid_id = ""

        # Lê em tempo real
        for line in proc.stdout:
            line = (line or "").rstrip()

            # Progresso
            m = rgx.search(line)
            if m:
                pct = float(m.group(1))
                total = m.group(2)
                speed = m.group(3) or ""
                eta   = m.group(4) or ""
                job_put(job_id, {"type": "progress", "percent": pct, "total": total, "speed": speed, "eta": eta})
                continue

            # Caminho final (após mover/merge) — vem via --print
            if line and ("/" in line or "\\" in line) and line.lower().endswith((".mp4", ".mkv", ".webm", ".mov")):
                final_path_str = line.strip()
                continue

            # ID impresso — heurística: se não parece path, guarda como id
            if line and not (("/" in line or "\\" in line) and line.lower().endswith((".mp4", ".mkv", ".webm", ".mov"))):
                vid_id = line.strip()

        ret = proc.wait()

        if ret != 0:
            raise subprocess.CalledProcessError(ret, cmd, output="")

        # Encontrar arquivo final
        final_path = None
        if final_path_str:
            p = Path(final_path_str)
            final_path = p if p.is_absolute() else (DOWNLOAD_DIR / p)
            if not final_path.is_file():
                final_path = None

        if not final_path and vid_id:
            candidates = sorted(DOWNLOAD_DIR.glob(f"*{vid_id}*"), key=lambda p: p.stat().st_mtime, reverse=True)
            for c in candidates:
                if c.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"} and c.is_file():
                    final_path = c
                    break

        if not final_path:
            time.sleep(0.3)
            new_files = [p for p in DOWNLOAD_DIR.glob("*") if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
            new_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for f in new_files:
                if f not in before or f.stat().st_mtime > before.get(f, 0):
                    final_path = f
                    break

        if not final_path:
            raise FileNotFoundError("Arquivo não encontrado após o download.")

        with JOBS_LOCK:
            JOBS[job_id]["file"] = final_path
            JOBS[job_id]["done"] = True
        job_put(job_id, {"type": "done", "filename": final_path.name})

    except subprocess.CalledProcessError as e:
        with JOBS_LOCK:
            JOBS[job_id]["error"] = "Falha no yt-dlp."
            JOBS[job_id]["done"] = True
        job_put(job_id, {"type": "error", "message": "Falha no yt-dlp. Veja logs e tente com cookies."})
    except Exception as e:
        with JOBS_LOCK:
            JOBS[job_id]["error"] = str(e)
            JOBS[job_id]["done"] = True
        job_put(job_id, {"type": "error", "message": str(e)})

# ===== Limpeza diária de downloads/ às 00:01 =====

def _clean_downloads_dir():
    """Remove tudo que está em downloads/ (arquivos e subpastas)."""
    for p in DOWNLOAD_DIR.iterdir():
        try:
            if p.is_file() or p.is_symlink():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            # não derruba o app por falha em um item
            pass

def _seconds_until_next_time(hh: int, mm: int, tzname: str) -> float:
    """Calcula segundos até o próximo horário hh:mm no fuso tzname."""
    tz = None
    if ZoneInfo:
        try:
            tz = ZoneInfo(tzname)
        except Exception:
            tz = None
    now = dt.datetime.now(tz) if tz else dt.datetime.now()
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now >= target:
        target = target + dt.timedelta(days=1)
    return max(1.0, (target - now).total_seconds())

def _daily_cleanup_worker():
    """Thread que limpa downloads todo dia no horário configurado."""
    tzname = os.getenv("TZ", "America/Sao_Paulo")
    # Override por env, formato HH:MM (ex.: 00:01)
    when = os.getenv("CLEANUP_TIME", "00:01")
    try:
        hh, mm = [int(x) for x in when.split(":", 1)]
    except Exception:
        hh, mm = 0, 1  # fallback 00:01

    while True:
        try:
            to_sleep = _seconds_until_next_time(hh, mm, tzname)
            time.sleep(to_sleep)
            _clean_downloads_dir()
        except Exception:
            # se algo der errado, espera 60s e tenta de novo
            time.sleep(60)

_cleanup_thread_started = False
def _start_cleanup_once():
    """Garante que a thread da limpeza diária inicia apenas uma vez no processo."""
    global _cleanup_thread_started
    if _cleanup_thread_started:
        return
    if os.getenv("CLEANUP_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        t = threading.Thread(target=_daily_cleanup_worker, daemon=True)
        t.start()
        _cleanup_thread_started = True

# inicia a faxina programada
_start_cleanup_once()

# ===== Rotas =====

@app.route("/", methods=["GET"])
def index():
    port = int(os.getenv("PORT", "8085"))
    has_cookies = (COOKIES_DIR / "cookies.txt").is_file()
    return render_template("index.html", port=port, has_cookies=has_cookies)

# Inicia um job e retorna job_id
@app.route("/start", methods=["POST"])
def start():
    url = (request.form.get("url") or "").strip()
    platform = detect_platform(url)
    if not url or not platform:
        return abort(400, description="URL inválida. Informe um link do TikTok, YouTube, Instagram ou Facebook.")

    # Cookie Header (textarea)
    cookie_header = (request.form.get("cookie_header") or "").strip()

    # cookies.txt (upload)
    cookie_path = None
    up = request.files.get("cookies")
    if up and up.filename:
        fname = secure_filename(up.filename)
        if not fname.lower().endswith(".txt"):
            return abort(400, description="Envie um arquivo cookies.txt no formato Netscape.")
        cookie_path = COOKIES_DIR / "cookies.txt"
        up.save(cookie_path)

    if not cookie_path:
        auto_cookie = COOKIES_DIR / "cookies.txt"
        if auto_cookie.is_file():
            cookie_path = auto_cookie

    output_template = "%(uploader|clean)s-%(title).160s-%(id)s.%(ext)s"
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    cmd = build_cmd(platform, url, user_agent, output_template)

    if cookie_header:
        cmd.extend(["--add-header", f"Cookie: {cookie_header}"])
    if cookie_path and Path(cookie_path).is_file():
        cmd.extend(["--cookies", str(cookie_path)])

    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {"queue": [], "done": False, "file": None, "error": None}

    t = threading.Thread(target=run_download, args=(job_id, cmd), daemon=True)
    t.start()

    return jsonify({"job_id": job_id})

# Stream de progresso via SSE
@app.route("/progress/<job_id>")
def progress(job_id):
    if job_id not in JOBS:
        return abort(404, description="Job não encontrado.")
    resp = Response(job_sse_stream(job_id), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"  # nginx friendly
    return resp

# Baixa o resultado do job
@app.route("/result/<job_id>")
def result(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return abort(404, description="Job não encontrado.")
    if job["error"]:
        return abort(500, description=job["error"])
    if not job["done"] or not job["file"]:
        return abort(409, description="Ainda processando. Aguarde.")
    f = job["file"]
    if not f.exists():
        return abort(410, description="Arquivo não está mais disponível.")
    return send_file(str(f), as_attachment=True, download_name=f.name)

# Rota de saúde (útil para testes/monitoramento)
@app.route("/healthz")
def healthz():
    return "ok", 200

# Erros em texto puro (evita HTML no front)
@app.errorhandler(400)
def handle_400(e):
    msg = getattr(e, "description", "Bad Request")
    return Response(str(msg), status=400, mimetype="text/plain; charset=utf-8")

@app.errorhandler(500)
def handle_500(e):
    msg = getattr(e, "description", "Internal Server Error")
    return Response(str(msg), status=500, mimetype="text/plain; charset=utf-8")

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8085"))
    app.run(host="0.0.0.0", port=port, threaded=True)
