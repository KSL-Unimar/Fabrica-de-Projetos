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

# Variáveis para armazenar os pontos da linha
pontos = []
imagem = frame.copy()


# Função para capturar os cliques do mouse
def selecionar_linha(event, x, y, flags, param):
    global imagem, pontos

    if event == cv2.EVENT_LBUTTONDOWN:

        # Armazena o ponto clicado
        pontos.append((x, y))

        # Desenha um círculo no ponto selecionado
        cv2.circle(imagem, (x, y), 5, (0, 0, 255), -1)

        # Quando dois pontos forem selecionados
        if len(pontos) == 2:

            # Coordenadas dos extremos da linha
            X1, Y1 = pontos[0]
            X2, Y2 = pontos[1]

            # Desenha a linha
            cv2.line(
                imagem,
                (X1, Y1),
                (X2, Y2),
                (0, 255, 0),
                2
            )

            print("\n--- COORDENADAS DA LINHA ---")
            print(f"X1 = {X1}")
            print(f"Y1 = {Y1}")
            print(f"X2 = {X2}")
            print(f"Y2 = {Y2}")

            # Reinicia para permitir selecionar outra linha
            pontos.clear()


# Cria a janela
cv2.namedWindow("Selecione as Linhas")

# Configura o evento do mouse
cv2.setMouseCallback("Selecione as Linhas", selecionar_linha)

print("Clique em dois pontos para desenhar uma linha.")
print("Pressione ESC para sair.")

while True:

    cv2.imshow("Selecione as Linhas", imagem)

    tecla = cv2.waitKey(1) & 0xFF

    # Sai ao pressionar ESC
    if tecla == 27:
        break

    # Pressione R para reiniciar a imagem
    if tecla == ord('r'):
        imagem = frame.copy()
        pontos.clear()

cap.release()
cv2.destroyAllWindows()