# CLIENTE DE ENVIO DE LEITURAS
#
# Envia a contagem de passageiros para o servidor.py (dashboard/banco) sem
# travar o loop da câmera: a última leitura fica em uma fila de tamanho 1 e é
# publicada por uma thread separada. Se o servidor estiver offline, o
# busScript.py continua funcionando normalmente.

import json
import queue
import threading
import time
import urllib.error
import urllib.request

URL_PADRAO = "http://127.0.0.1:8000"
ONIBUS_PADRAO = "onibus-01"


class ClienteLotacao:
    """Publica leituras de lotação em segundo plano (não bloqueante)."""

    def __init__(
        self,
        url=URL_PADRAO,
        onibus=ONIBUS_PADRAO,
        timeout=2.0,
        intervalo_aviso=30.0,
    ):
        self.url = url.rstrip("/") + "/api/leituras"
        self.onibus = onibus
        self.timeout = timeout
        self.intervalo_aviso = intervalo_aviso

        self.enviados = 0
        self.falhas = 0

        # Fila de 1: leituras novas descartam a antiga ainda pendente
        self._fila = queue.Queue(maxsize=1)
        self._parar = threading.Event()
        self._ultimo_aviso = 0.0
        self._thread = threading.Thread(
            target=self._laco, name="cliente-lotacao", daemon=True
        )
        self._thread.start()

    def enviar(self, passageiros, capacidade, viagem="", linha=""):
        """Enfileira uma leitura (passageiros/capacidade puros; o servidor classifica)."""
        dados = {
            "onibus": self.onibus,
            "passageiros": int(passageiros),
            "capacidade": int(capacidade),
            "viagem": str(viagem),
            "linha": str(linha),
        }
        try:
            self._fila.put_nowait(dados)
        except queue.Full:
            try:
                self._fila.get_nowait()
            except queue.Empty:
                pass
            self._fila.put_nowait(dados)
        return dados

    def fechar(self, esperar=3.0):
        """Tenta publicar o que estiver pendente e encerra a thread."""
        self._parar.set()
        self._thread.join(timeout=esperar)

    def _laco(self):
        while True:
            try:
                dados = self._fila.get(timeout=0.5)
            except queue.Empty:
                if self._parar.is_set():
                    return
                continue
            self._postar(dados)

    def _postar(self, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        requisicao = urllib.request.Request(
            self.url,
            data=corpo,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=self.timeout) as resposta:
                resposta.read()
            self.enviados += 1
        except (urllib.error.URLError, OSError, ValueError) as erro:
            self.falhas += 1
            agora = time.monotonic()
            if agora - self._ultimo_aviso >= self.intervalo_aviso:
                self._ultimo_aviso = agora
                print(f"[lotacao] servidor indisponível em {self.url}: {erro}")
