#!/usr/bin/env python3
"""dvr_agent.py — captura frames de DVR Intelbras e salva localmente ou envia para API."""

import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from requests.auth import HTTPDigestAuth

# ─── ANSI helpers ─────────────────────────────────────────────────────────────
# Detecta se a saída é um terminal real.
# Se não for (ex: serviço do Windows), desativa os códigos de cor ANSI
# para que o log não fique cheio de caracteres estranhos.

_TTY = sys.stdout.isatty()

def _esc(code: str) -> str:
    return f"\033[{code}" if _TTY else ""

RST  = _esc("0m");  BOLD = _esc("1m");  DIM  = _esc("2m")
CYN  = _esc("36m"); CY2  = _esc("96m")
GRN  = _esc("32m"); GR2  = _esc("92m")
RED  = _esc("31m"); RE2  = _esc("91m")
YLW  = _esc("33m")


# ─── Config ───────────────────────────────────────────────────────────────────
# Quando empacotado com PyInstaller (frozen=True), o executável fica em um
# diretório temporário (_MEIPASS). Para não perder o config.json ao reiniciar,
# ele é guardado em %APPDATA%\DVR Agent CAMAI\.
# Na primeira execução copia o config.json embutido no instalador para lá.

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        appdata = Path(os.environ.get("APPDATA", Path.home())) / "DVR Agent CAMAI"
        appdata.mkdir(parents=True, exist_ok=True)
        if not (appdata / "config.json").exists():
            bundled = Path(sys.executable).parent / "config.json"
            if bundled.exists():
                import shutil
                shutil.copy(bundled, appdata / "config.json")
        return appdata
    return Path(__file__).parent  # modo desenvolvimento: mesma pasta do .py


def load_config() -> dict:
    # Lê e valida o config.json. Campos obrigatórios variam conforme o modo
    # (local ou api). Se faltar algum campo, o agente para com mensagem clara.
    path = _base_dir() / "config.json"
    if not path.exists():
        sys.exit(f"Erro: config.json não encontrado em {path}")
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"Erro ao parsear config.json: {exc}")

    mode = cfg.get("mode", "api")
    if mode == "local":
        required = {"dvr_ip", "dvr_user", "dvr_pass", "local_path", "interval_seconds", "cameras"}
    else:
        required = {"dvr_ip", "dvr_user", "dvr_pass", "ingest_url", "ingest_key", "interval_seconds", "cameras"}

    if miss := required - cfg.keys():
        sys.exit(f"Campos ausentes em config.json para mode='{mode}': {miss}")
    return cfg


# ─── Banner ───────────────────────────────────────────────────────────────────
# Exibe um quadro visual no terminal ao iniciar, mostrando todas as
# configurações ativas: IP, modo, intervalo, câmeras, detecção de movimento.

def print_banner(cfg: dict) -> None:
    mode = cfg.get("mode", "api")
    dest = cfg["local_path"] if mode == "local" else cfg["ingest_url"]
    motion_tag = "SIM (só captura com movimento)" if cfg.get("motion_detection") else "NÃO (captura sempre)"
    lines = [
        "  DVR AGENT  ·  Intelbras Frame Capture  ",
        "",
        f"  DVR IP    : {cfg['dvr_ip']}",
        f"  Modo      : {'LOCAL  → ' + dest if mode == 'local' else 'API    → ' + dest}",
        f"  Intervalo : {cfg['interval_seconds']}s     Câmeras: {len(cfg['cameras'])}",
        f"  Movimento : {motion_tag}",
        "",
    ]
    for c in cfg["cameras"]:
        lines.append(f"    [{c['cam_id']:>6s}]  canal {c['channel']}  zona: {c['zone']}")
    lines.append("")

    w = max(len(l) for l in lines) + 2

    def row(text: str, color: str = CY2) -> str:
        pad = w - len(text)
        return f"{CYN}║{RST}{color}{text}{RST}{' ' * pad}{CYN}║{RST}"

    print(f"{CYN}╔{'═' * w}╗{RST}")
    for i, line in enumerate(lines):
        c = BOLD + CY2 if i == 0 else CY2
        print(row(line, c))
    print(f"{CYN}╚{'═' * w}╝{RST}\n")


# ─── Motion detection ─────────────────────────────────────────────────────────
# Consulta o endpoint CGI do DVR para saber se há movimento em um canal.
#
# O firmware Intelbras/Dahua expõe dois formatos de resposta:
#   1. getAllAlarmStatus → lista todos os alarmes ativos de todos os canais
#   2. getMotionDetectState → estado de um canal específico
#
# ATENÇÃO: o DVR usa canal base-0 no CGI (Canal 1 da UI = channel=0 na URL).
# Por isso tentamos ch0 = channel - 1 além do valor original.
#
# A variável _motion_endpoint armazena qual URL funcionou para evitar
# tentar as outras a cada ciclo (cache em memória).

_motion_endpoint: str | None = None


def _query_alarm(cfg: dict, channel: int) -> tuple[bool, str, str]:
    """Consulta o endpoint CGI de alarme. Retorna (active, url, raw_body)."""
    global _motion_endpoint
    auth = HTTPDigestAuth(cfg["dvr_user"], cfg["dvr_pass"])
    base = f"http://{cfg['dvr_ip']}"
    ch0  = channel - 1  # Intelbras/Dahua usa base-0 no CGI

    candidates = [
        f"{base}/cgi-bin/alarm.cgi?action=getAllAlarmStatus",
        f"{base}/cgi-bin/alarm.cgi?action=getMotionDetectState&channel={ch0}",
        f"{base}/cgi-bin/alarm.cgi?action=getMotionDetectState&channel={channel}",
    ]
    # Coloca o endpoint que funcionou antes no topo da lista
    if _motion_endpoint:
        candidates = [_motion_endpoint] + [u for u in candidates if u != _motion_endpoint]

    last_err = "nenhuma URL tentada"
    for url in candidates:
        action = url.split("action=")[-1][:40]
        try:
            r = requests.get(url, auth=auth, timeout=5)
            if r.status_code == 200:
                _motion_endpoint = url
                active = _parse_motion(r.text, channel, ch0)
                return active, url, r.text
            last_err = f"HTTP {r.status_code} em ?action={action}"
        except requests.exceptions.Timeout:
            last_err = f"timeout em ?action={action}"
        except requests.RequestException as exc:
            last_err = f"{type(exc).__name__} em ?action={action}"

    return False, "", f"[ERRO] {last_err}"


def _motion_active(cfg: dict, channel: int) -> bool:
    active, _url, _body = _query_alarm(cfg, channel)
    return active


def _parse_motion(body: str, channel: int, ch0: int) -> bool:
    """Interpreta a resposta CGI do DVR.

    Só retorna True se encontrar EXPLICITAMENTE type=MotionDetect + status=1.
    Tenta channel (1-based) e ch0 (0-based) para cobrir variações de firmware.
    Não usa fallback genérico — evita falsos positivos de outros alarmes
    como VideoLoss, que também têm status=1.
    """
    # Formato getAllAlarmStatus: divide em blocos por índice de alarme
    blocks = re.split(r"alarms\[\d+\]\.", body)
    for block in blocks:
        ch_m  = re.search(r"channel=(\d+)", block)
        typ_m = re.search(r"type=(\w+)", block)
        sts_m = re.search(r"status=(\d+)", block)
        if ch_m and int(ch_m.group(1)) in (channel, ch0):
            if typ_m and "motion" in typ_m.group(1).lower():
                return sts_m is not None and sts_m.group(1) == "1"

    # Formato getMotionDetectState (resposta de canal único)
    if re.search(r"MotionDetect.*?status\s*=\s*1", body, re.IGNORECASE | re.DOTALL):
        return True

    return False


# ─── DVR capture ──────────────────────────────────────────────────────────────
# Faz GET no endpoint de snapshot do DVR usando HTTP Digest Auth
# (protocolo padrão Intelbras/Dahua). Retorna o JPEG em bytes.

def capture(cfg: dict, channel: int) -> bytes:
    url = f"http://{cfg['dvr_ip']}/cgi-bin/snapshot.cgi?channel={channel}"
    r = requests.get(
        url,
        auth=HTTPDigestAuth(cfg["dvr_user"], cfg["dvr_pass"]),
        timeout=10,
    )
    r.raise_for_status()  # lança exceção para HTTP 4xx/5xx
    return r.content


# ─── Armazenamento local ──────────────────────────────────────────────────────
# Salva o JPEG em disco na estrutura: local_path / cam_id / cam_id_YYYYMMDD_HHMMSS.jpg

def save_local(cfg: dict, cam_id: str, data: bytes) -> str:
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(cfg["local_path"]) / cam_id
    root.mkdir(parents=True, exist_ok=True)  # cria a pasta se não existir
    dest = root / f"{cam_id}_{ts}.jpg"
    dest.write_bytes(data)
    return str(dest)


# ─── API ingest ───────────────────────────────────────────────────────────────
# Envia o frame para a API da CAMAI.
# O JPEG é codificado em Base64 e enviado num JSON junto com cam_id e zone.
# A API responde 202 Accepted com o frame_id gerado.

def ingest(cfg: dict, cam_id: str, zone: str, data: bytes) -> str:
    b64 = base64.b64encode(data).decode()
    resp = requests.post(
        cfg["ingest_url"],
        json={"cam_id": cam_id, "zone": zone, "image": b64},
        headers={"X-Api-Key": cfg["ingest_key"]},
        timeout=15,
    )
    if resp.status_code != 202:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:100]}")
    try:
        body = resp.json()
        return str(body.get("frame_id") or body.get("id") or "—")
    except Exception:
        return "—"


# ─── Despacho por modo ────────────────────────────────────────────────────────
# Centraliza a decisão de salvar local ou enviar para API.

def store(cfg: dict, cam: dict, data: bytes) -> str:
    if cfg.get("mode", "api") == "local":
        return save_local(cfg, cam["cam_id"], data)
    return ingest(cfg, cam["cam_id"], cam["zone"], data)


# ─── Terminal UI ──────────────────────────────────────────────────────────────
# Funções de impressão colorida no terminal.
# Usam \r (carriage return) para sobrescrever a linha atual durante
# o processamento, exibindo o resultado final quando concluído.

def _hdr(cycle: int, n_cams: int) -> None:
    # Cabeçalho de cada ciclo com número e horário
    ...

def _working(cam: dict, msg: str = "capturando...") -> None:
    # Linha temporária mostrando o que está acontecendo (sobrescrita pelo resultado)
    ...

def _cam_ok(cam: dict, detail: str, kb: float, ms: float, mode: str = "api") -> None:
    # Linha verde de sucesso com nome do arquivo, tamanho e latência
    ...

def _cam_err(cam: dict, msg: str) -> None:
    # Linha vermelha com a mensagem de erro
    ...

def _cam_skip(cam: dict, snippet: str = "") -> None:
    # Linha cinza indicando que o frame foi ignorado (sem movimento)
    ...

def _summary(ok: int, total: int, elapsed: float, interval: int) -> None:
    # Barra de progresso visual + contagem de sucessos/falhas ao fim do ciclo
    ...

def _countdown(seconds: float) -> None:
    # Contagem regressiva animada até o próximo ciclo
    ...


# ─── Main loop ────────────────────────────────────────────────────────────────
# Loop infinito: a cada ciclo percorre todas as câmeras configuradas.
#
# Fluxo com motion_detection = true:
#   1. Consulta CGI de alarme do canal
#   2. Se sem movimento → _cam_skip e próxima câmera
#   3. Se com movimento → captura JPEG → salva/envia → _cam_ok
#
# Fluxo com motion_detection = false:
#   1. Captura JPEG diretamente → salva/envia → _cam_ok
#
# O intervalo de espera entre ciclos é:
#   - motion_poll_seconds (padrão 2s) quando detecção de movimento está ativa
#   - interval_seconds (padrão 30s) quando captura contínua

def run(cfg: dict) -> None:
    cameras     = cfg["cameras"]
    interval    = int(cfg["interval_seconds"])
    mode        = cfg.get("mode", "api")
    motion_only = cfg.get("motion_detection", False)
    poll_secs   = int(cfg.get("motion_poll_seconds", 2)) if motion_only else interval
    cycle       = 0

    while True:
        cycle += 1
        _hdr(cycle, len(cameras))
        t_start = time.monotonic()
        ok = 0

        for cam in cameras:
            _working(cam)
            t0 = time.monotonic()
            try:
                if motion_only:
                    _working(cam, "verificando alarme...")
                    active, url, raw = _query_alarm(cfg, cam["channel"])
                    snippet = raw.replace("\n", " ").replace("\r", "")[:80]
                    if not active:
                        _cam_skip(cam, snippet)
                        continue  # pula a captura

                img    = capture(cfg, cam["channel"])
                action = "salvando..." if mode == "local" else "enviando..."
                _working(cam, action)
                detail = store(cfg, cam, img)
                _cam_ok(cam, detail, len(img)/1024, (time.monotonic()-t0)*1000, mode)
                ok += 1
            except Exception as exc:
                _cam_err(cam, str(exc))

        elapsed = time.monotonic() - t_start
        _summary(ok, len(cameras), elapsed, poll_secs)
        _countdown(max(0.0, poll_secs - elapsed))


def main() -> None:
    cfg = load_config()
    print_banner(cfg)
    try:
        run(cfg)
    except KeyboardInterrupt:
        # Encerramento limpo com Ctrl+C
        sys.exit(0)


if __name__ == "__main__":
    main()
