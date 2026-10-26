#!/usr/bin/env python3
"""dvr_monitor.py — DVR Agent CAMAI com painel de monitoramento em tempo real."""

# As mesmas funções de config, capture, motion detection, save_local,
# ingest e store do dvr_agent.py estão presentes aqui também,
# pois o monitor executa o agente internamente via thread.

# ─── AgentWorker ──────────────────────────────────────────────────────────────
# Thread de fundo que executa o loop de captura.
#
# Comunicação com a GUI: em vez de imprimir no terminal, coloca dicionários
# numa queue.Queue. A GUI consome essa fila a cada 80ms via root.after().
#
# Tipos de eventos emitidos:
#   cycle_start  → início de um novo ciclo (atualiza título e log)
#   working      → câmera em processamento (atualiza status na tabela)
#   alarm_result → resultado da consulta CGI (log com MOVIMENTO ou sem mov.)
#   ok           → frame capturado com sucesso (verde na tabela e no log)
#   err          → falha na captura (vermelho na tabela e no log)
#   skip         → movimento não detectado, frame ignorado (cinza)
#   cycle_end    → fim do ciclo com contagem de sucessos
#   countdown    → contagem regressiva até o próximo ciclo

class AgentWorker(threading.Thread):
    def __init__(self, cfg: dict, q: queue.Queue) -> None:
        super().__init__(daemon=True)  # daemon=True: encerra junto com a janela
        self.cfg   = cfg
        self.q     = q
        self._stop = threading.Event()  # sinal de parada sem matar a thread brutalmente

    def stop(self) -> None:
        self._stop.set()  # sinaliza parada; o loop verifica a cada iteração

    def run(self) -> None:
        cameras     = self.cfg["cameras"]
        interval    = int(self.cfg["interval_seconds"])
        motion_only = self.cfg.get("motion_detection", False)
        poll_secs   = int(self.cfg.get("motion_poll_seconds", 2)) if motion_only else interval
        cycle       = 0

        while not self._stop.is_set():
            cycle += 1
            self.q.put({"type": "cycle_start", "cycle": cycle, ...})

            for cam in cameras:
                if self._stop.is_set():
                    break
                try:
                    if motion_only:
                        active, url, raw = _query_alarm(self.cfg, cam["channel"])
                        self.q.put({"type": "alarm_result", "cam": cam, "active": active, ...})
                        if not active:
                            self.q.put({"type": "skip", "cam": cam})
                            continue

                    img    = capture(self.cfg, cam["channel"])
                    detail = store(self.cfg, cam, img)
                    self.q.put({"type": "ok", "cam": cam, "detail": detail, ...})
                except Exception as exc:
                    self.q.put({"type": "err", "cam": cam, "msg": str(exc)})

            # Aguarda o próximo ciclo em intervalos de 0.5s,
            # verificando _stop a cada iteração para parada rápida
            end = time.monotonic() + wait
            while not self._stop.is_set():
                if end - time.monotonic() <= 0:
                    break
                self.q.put({"type": "countdown", "rem": end - time.monotonic()})
                self._stop.wait(timeout=0.5)


# ─── MonitorApp ───────────────────────────────────────────────────────────────
# Classe principal da GUI. Usa Tkinter com tema escuro (GitHub Dark).
#
# Layout em 4 camadas empilhadas (pack):
#   1. Header    → título, info do DVR, status (RODANDO/PAUSADO), botão ⚙
#   2. CycleBar  → número do ciclo, barra de progresso, botão ▶/⏸
#   3. CamTable  → ttk.Treeview com uma linha por câmera
#   4. LogPanel  → tk.Text com log colorido por tags + toolbar

class MonitorApp:
    def __init__(self, root: tk.Tk, cfg: dict) -> None:
        self.root   = root
        self.cfg    = cfg
        self.q      = queue.Queue()   # canal de comunicação com o worker
        self.worker = None
        self._build_ui()
        self._start_worker()
        self._poll()  # inicia o ciclo de leitura da fila

    def _poll(self) -> None:
        # Consome todos os eventos disponíveis na fila sem bloquear.
        # Reagenda a si mesmo a cada 80ms (≈12 fps de atualização da UI).
        try:
            while True:
                self._handle(self.q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _handle(self, ev: dict) -> None:
        # Despacha cada tipo de evento para a ação correta na GUI.
        # Exemplo: ev["type"] == "ok" → atualiza linha verde na tabela
        #          ev["type"] == "err" → atualiza linha vermelha
        #          ev["type"] == "countdown" → atualiza contador no CycleBar
        ...

    def _toggle_agent(self) -> None:
        # Pausa ou retoma o worker. Ao pausar, chama worker.stop()
        # e aguarda a thread terminar graciosamente.
        ...

    def _apply_settings(self, new_cfg: dict) -> None:
        # Chamado pelo SettingsDialog ao salvar.
        # Persiste o config.json e reinicia o worker com as novas configurações.
        self.cfg = new_cfg
        save_config(new_cfg)
        self._restart_worker()


# ─── SettingsDialog ───────────────────────────────────────────────────────────
# Modal de configuração. Abre centralizado sobre a janela principal.
# grab_set() bloqueia a janela pai enquanto o modal está aberto.
#
# Campos:
#   DVR IP / Porta / Usuário / Senha (com 👁 para mostrar/ocultar)
#   Intervalo de captura (segundos)
#   ☑ Capturar somente com movimento detectado
#      ↳ Verificar alarme a cada [2] s
#   Armazenamento: ● Local (disco)  ○ VPS / API
#      Local → campo de pasta
#      API   → URL + Chave
#   Editor de câmeras (linhas dinâmicas com cam_id, canal, zona, botão ×)
#
# Botões de diagnóstico:
#   [Testar conexão] → faz snapshot da 1ª câmera, exibe KB capturado
#   [Testar alarme]  → abre janela com resposta bruta do CGI de alarme
#
# Botões de ação:
#   [Salvar]   → chama _read_fields() + on_save(new_cfg) + fecha o modal
#   [Cancelar] → fecha sem salvar

class SettingsDialog:
    def _read_fields(self) -> dict:
        # Lê todos os campos do formulário e monta o dict de config.
        # Valida campos obrigatórios e lança ValueError com mensagem clara
        # para exibição no test_lbl (sem fechar o modal).
        ...

    def _test_alarm(self) -> None:
        # Abre uma janela de diagnóstico com a resposta bruta do CGI:
        #   URL   : http://192.168.1.100/cgi-bin/alarm.cgi?action=getAllAlarmStatus
        #   Status: – Sem movimento  (ou ▲ MOVIMENTO DETECTADO)
        #   Resposta:
        #   alarms.count=4
        #   alarms[0].channel=0
        #   alarms[0].type=MotionDetect
        #   alarms[0].status=0
        ...


# ─── Main ─────────────────────────────────────────────────────────────────────
# Carrega config, cria a janela Tkinter e instala um handler global de erros.
#
# root.report_callback_exception é sobrescrito para exibir um messagebox
# quando qualquer callback do Tkinter lança uma exceção.
# Isso é crítico no modo --noconsole (exe sem terminal), onde exceções
# silenciosas deixariam a UI travada sem nenhuma mensagem visível.

def main() -> None:
    cfg  = load_config()
    root = tk.Tk()

    def _on_tk_error(exc, val, tb):
        msg = "".join(traceback.format_exception(exc, val, tb))
        mb.showerror("Erro inesperado", msg[:800])

    root.report_callback_exception = _on_tk_error

    MonitorApp(root, cfg)
    root.mainloop()
