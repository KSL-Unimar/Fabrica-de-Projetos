# DETECTOR DE PASSAGEIROS (YOLO + CRUZAMENTO DE LINHA)
#
# Este módulo só sabe detectar pessoas e contar cruzamentos da linha.
# A lógica do ônibus (parado, portas, lotação) fica no busScript.py.

import math
from pathlib import Path

import cv2
from ultralytics import YOLO

# CAMINHO DO MODELO (funciona independente do diretório atual)
MODELO = str(Path(__file__).resolve().parent / "yolo11n.pt")

# LINHA DE CONTAGEM (coordenadas obtidas com getROILines.py)
LINHA_X1 = 617
LINHA_Y1 = 219
LINHA_X2 = 617
LINHA_Y2 = 528

# Lado considerado "dentro do ônibus" (inverta para 1 se entrada/saída trocarem)
LADO_ENTRADA = -1

# Distância mínima (px) para confirmar o lado e evitar tremor sobre a linha
MARGEM = 6

# Frames sem detecção antes de esquecer um ID
FRAMES_PARA_ESQUECER = 150


def lado_da_linha(cx, cy, x1, y1, x2, y2):
    # O sinal indica o lado da reta; a magnitude é proporcional à distância
    return (x2 - x1) * (cy - y1) - (y2 - y1) * (cx - x1)


def cruza_segmento(p_antes, p_agora, x1, y1, x2, y2):
    # Verifica se o trajeto p_antes -> p_agora cruza o segmento da linha
    px, py = p_antes
    qx, qy = p_agora
    rx, ry = qx - px, qy - py
    sx, sy = x2 - x1, y2 - y1

    denom = rx * sy - ry * sx
    if denom == 0:
        return False

    qpx, qpy = x1 - px, y1 - py
    t = (qpx * sy - qpy * sx) / denom
    u = (qpx * ry - qpy * rx) / denom

    return 0 <= t <= 1 and 0 <= u <= 1


class DetectorPassageiros:
    """Detecta pessoas e conta cruzamentos da linha, mantendo os IDs."""

    def __init__(
        self,
        linha=None,
        lado_entrada=LADO_ENTRADA,
        margem=MARGEM,
        conf=0.5,
        modelo=MODELO,
    ):
        if linha is None:
            linha = (LINHA_X1, LINHA_Y1, LINHA_X2, LINHA_Y2)

        self.linha = linha
        self.lado_entrada = lado_entrada
        self.margem = margem
        self.conf = conf
        self.model = YOLO(modelo)

        lx1, ly1, lx2, ly2 = linha
        self.comprimento = math.hypot(lx2 - lx1, ly2 - ly1)

        self.entradas = 0
        self.saidas = 0

        # track_id -> (lado, último ponto confirmado)
        self.estado = {}

        # track_id -> último frame em que apareceu
        self.ultimo_frame = {}

        self.frame_atual = 0

    def resetar(self):
        # Zera o rastreamento (ex.: ao fechar as portas)
        self.estado.clear()
        self.ultimo_frame.clear()
        self.frame_atual = 0

    def processar(self, frame, lado_entrada=None):
        """Processa um frame e devolve (frame anotado, entradas, saidas).

        lado_entrada permite sobrescrever o sentido definido no construtor
        (-1 ou 1).
        """
        if lado_entrada is not None:
            self.lado_entrada = lado_entrada

        self.frame_atual += 1

        entradas_frame = 0
        saidas_frame = 0

        # persist=True mantém o ID das pessoas entre os frames
        results = self.model.track(
            frame,
            persist=True,
            classes=[0],
            conf=self.conf,
            tracker="bytetrack.yaml",
            verbose=False,
        )

        annotated = results[0].plot()
        boxes = results[0].boxes

        if boxes.id is not None:
            ids = boxes.id.int().tolist()
            caixas = boxes.xyxy.int().tolist()

            for track_id, (bx1, by1, bx2, by2) in zip(ids, caixas):
                self.ultimo_frame[track_id] = self.frame_atual

                # Ponto central da pessoa
                cx = (bx1 + bx2) // 2
                cy = (by1 + by2) // 2

                sinal = lado_da_linha(cx, cy, *self.linha)

                # Distância em pixels até a linha
                distancia = sinal / self.comprimento

                # Em cima da linha: mantém o lado anterior (histerese)
                if abs(distancia) < self.margem:
                    continue

                lado_atual = 1 if distancia > 0 else -1
                anterior = self.estado.get(track_id)

                if anterior is not None:
                    lado_antes, ponto_antes = anterior

                    if (
                        lado_atual != lado_antes
                        and cruza_segmento(ponto_antes, (cx, cy), *self.linha)
                    ):
                        if lado_atual == self.lado_entrada:
                            entradas_frame += 1
                        else:
                            saidas_frame += 1

                self.estado[track_id] = (lado_atual, (cx, cy))

        # Esquece IDs que sumiram da cena
        for track_id in list(self.estado):
            if (
                self.frame_atual - self.ultimo_frame.get(track_id, self.frame_atual)
                > FRAMES_PARA_ESQUECER
            ):
                del self.estado[track_id]
                self.ultimo_frame.pop(track_id, None)

        self.entradas += entradas_frame
        self.saidas += saidas_frame

        self.desenhar_linha(annotated)

        return annotated, entradas_frame, saidas_frame

    def desenhar_linha(self, frame):
        cv2.line(frame, self.linha[:2], self.linha[2:], (0, 255, 255), 2)
