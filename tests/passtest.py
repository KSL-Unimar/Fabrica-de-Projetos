from ultralytics import YOLO
import cv2

model = YOLO("yolo11n.pt")

cap = cv2.VideoCapture(0)

# =========================
# ÁREA / QUADRADO
# =========================

ROI_X1 = 300
ROI_Y1 = 200

ROI_X2 = 600
ROI_Y2 = 500


def pessoa_entrou():
    print("PESSOA ENTROU NA ÁREA!")


pessoa_dentro_anteriormente = False


while True:

    ret, frame = cap.read()

    if not ret:
        break

    results = model(
        frame,
        classes=[0],
        conf=0.5,
        verbose=False
    )

    # Desenha o quadrado
    cv2.rectangle(
        frame,
        (ROI_X1, ROI_Y1),
        (ROI_X2, ROI_Y2),
        (0, 255, 0),
        2
    )

    pessoa_dentro = False

    for box in results[0].boxes:

        x1, y1, x2, y2 = map(
            int,
            box.xyxy[0]
        )

        # =========================
        # PONTO CENTRAL DA PESSOA
        # =========================

        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2

        # Ponto vermelho no centro
        cv2.circle(
            frame,
            (cx, cy),
            6,
            (0, 0, 255),
            -1
        )

        # Verifica se o centro está dentro do quadrado
        if (
            ROI_X1 <= cx <= ROI_X2
            and
            ROI_Y1 <= cy <= ROI_Y2
        ):
            pessoa_dentro = True

        # Bounding box da pessoa
        cv2.rectangle(
            frame,
            (x1, y1),
            (x2, y2),
            (255, 0, 0),
            2
        )

    # Chama a função somente quando entra
    if pessoa_dentro and not pessoa_dentro_anteriormente:
        pessoa_entrou()

    pessoa_dentro_anteriormente = pessoa_dentro

    # Status
    if pessoa_dentro:
        texto = "PESSOA NA AREA"
        cor = (0, 255, 0)
    else:
        texto = "AREA LIVRE"
        cor = (0, 0, 255)

    cv2.putText(
        frame,
        texto,
        (ROI_X1, ROI_Y1 - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        cor,
        2
    )

    cv2.imshow("YOLO + Iriun", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


cap.release()
cv2.destroyAllWindows()