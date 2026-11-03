
import cv2

# Abre a câmera
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Erro: não foi possível abrir a câmera.")
    exit()

# Captura uma imagem
ret, frame = cap.read()

if not ret:
    print("Erro ao capturar imagem.")
    cap.release()
    exit()

# Permite selecionar a ROI com o mouse
# Arraste o mouse para desenhar o retângulo
roi = cv2.selectROI(
    "Selecione a ROI",
    frame,
    showCrosshair=True,
    fromCenter=False
)

# ROI retorna: x, y, largura, altura
x, y, largura, altura = roi

# Calcula as coordenadas dos dois cantos
ROI_X1 = x
ROI_Y1 = y
ROI_X2 = x + largura
ROI_Y2 = y + altura

print("\n--- COORDENADAS DA ROI ---")
print(f"ROI_X1 = {ROI_X1}")
print(f"ROI_Y1 = {ROI_Y1}")
print(f"ROI_X2 = {ROI_X2}")
print(f"ROI_Y2 = {ROI_Y2}")

# Desenha a região selecionada
cv2.rectangle(
    frame,
    (ROI_X1, ROI_Y1),
    (ROI_X2, ROI_Y2),
    (0, 255, 0),
    2
)

cv2.imshow("ROI Selecionada", frame)

print("\nPressione qualquer tecla na janela para fechar.")

cv2.waitKey(0)

cap.release()
cv2.destroyAllWindows()
