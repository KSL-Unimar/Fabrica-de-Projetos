from ultralytics import YOLO
import cv2

model = YOLO("yolo11n.pt")

cap = cv2.VideoCapture(0)  # tente 1 ou 2 se o Iriun não estiver no 0

while True:
    ret, frame = cap.read()
    if not ret:
        break

    #0results = model(frame)
    results = model(frame, classes=[0], conf=0.5)
    annotated = results[0].plot()

    cv2.imshow("YOLO + Iriun", annotated)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()