# SIMULAÇÃO DE ÔNIBUS REAL
#
# Estados do ônibus:
#   EM MOVIMENTO (portas fechadas) -> não conta
#   PARADO, portas fechadas         -> não conta
#   PARADO, portas abertas          -> conta entradas e saídas
#
# Teclas:
#   p = parar / partir
#   o = abrir / fechar portas (só quando parado)
#   q = sair e mostrar o resumo
#
# O detector de pessoas fica no detector_passageiros.py.

import cv2

from detector_passageiros import DetectorPassageiros

LIMITE = 40
PASSAGEIROS_INICIAIS = 0

# Sentido da linha: -1 ou 1 (inverta se entrada/saída aparecerem trocadas)
SENTIDO_ENTRADA = 1


def check_limite(passageiros, limite=LIMITE):
    return passageiros >= limite


def atualizar_passageiros(passageiros, situacao):
    match situacao:
        case 1:
            passageiros += 1
        case 2:
            passageiros -= 1
    return max(0, passageiros)


def parada_acionada(tecla):
    return tecla == ord("p")


def check_parada(parado):
    return parado


def check_portas(portas_abertas):
    return portas_abertas


def detectar_passagem(entradas):
    return entradas > 0


def detectar_saida(saidas):
    return saidas > 0


def desenhar_painel(frame, passageiros, parado, portas_abertas, lotado):
    if not check_parada(parado):
        status = "EM MOVIMENTO"
        cor = (0, 255, 255)
    elif not check_portas(portas_abertas):
        status = "PARADO - PORTAS FECHADAS"
        cor = (0, 255, 255)
    else:
        status = "PARADO - PORTAS ABERTAS"
        cor = (0, 255, 0)

    cv2.putText(
        frame,
        status,
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        cor,
        2
    )

    cv2.putText(
        frame,
        f"Passageiros: {passageiros}/{LIMITE}",
        (20, 75),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 0),
        2
    )

    if lotado:
        cv2.putText(
            frame,
            "LOTADO",
            (20, 115),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 0, 255),
            2
        )

    cv2.putText(
        frame,
        "p=parar/partir  o=portas  q=sair",
        (20, frame.shape[0] - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        1
    )


def main():
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Erro: não foi possível abrir a câmera.")
        return

    detector = DetectorPassageiros(lado_entrada=SENTIDO_ENTRADA)

    passageiros = PASSAGEIROS_INICIAIS
    parado = False
    portas_abertas = False
    lotado_anterior = False

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        tecla = cv2.waitKey(1) & 0xFF

        if tecla == ord("q"):
            break

        # 'p' alterna entre parado e em movimento
        if parada_acionada(tecla):
            if check_parada(parado):
                # Parte: fecha as portas e volta a andar
                portas_abertas = False
                parado = False
                detector.resetar()
            else:
                parado = True

        # 'o' abre/fecha as portas somente com o ônibus parado
        if tecla == ord("o") and check_parada(parado):
            portas_abertas = not portas_abertas
            detector.resetar()

        entradas_frame = 0
        saidas_frame = 0

        # A contagem só roda com o ônibus parado e as portas abertas
        if check_parada(parado) and check_portas(portas_abertas):
            annotated, entradas_frame, saidas_frame = detector.processar(
                frame, SENTIDO_ENTRADA
            )

            for _ in range(entradas_frame):
                passageiros = atualizar_passageiros(passageiros, 1)

            for _ in range(saidas_frame):
                passageiros = atualizar_passageiros(passageiros, 2)

            if detectar_passagem(entradas_frame):
                print(f"Entrada detectada. Passageiros: {passageiros}")

            if detectar_saida(saidas_frame):
                print(f"Saída detectada. Passageiros: {passageiros}")
        else:
            annotated = frame
            detector.desenhar_linha(annotated)

        lotado = check_limite(passageiros, LIMITE)

        if lotado and not lotado_anterior:
            print("Ônibus lotado!")

        lotado_anterior = lotado

        desenhar_painel(annotated, passageiros, parado, portas_abertas, lotado)

        cv2.imshow("Simulacao Onibus", annotated)

    cap.release()
    cv2.destroyAllWindows()

    print("\n--- RESUMO DA VIAGEM ---")
    print(f"Entradas: {detector.entradas}")
    print(f"Saídas: {detector.saidas}")
    print(f"Passageiros no ônibus: {passageiros}")


if __name__ == "__main__":
    main()
