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
# A classificação de lotação fica no superlotacao.py e é enviada ao
# servidor.py (API + dashboard + SQLite) pelo cliente_api.py.
#
# Uso:
#   .venv/bin/python busScript.py                 # mostra a lista e pede o ônibus
#   .venv/bin/python busScript.py --onibus onibus-01
#   .venv/bin/python busScript.py --servidor http://192.168.0.10:8000

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime

import cv2

import superlotacao
from cliente_api import ClienteLotacao
from detector_passageiros import DetectorPassageiros

LIMITE = 40
PASSAGEIROS_INICIAIS = 0

# Sentido da linha: -1 ou 1 (inverta se entrada/saída aparecerem trocadas)
SENTIDO_ENTRADA = 1

# Envio para o servidor/dashboard (rode `servidor.py` para ver no navegador)
URL_SERVIDOR = "http://127.0.0.1:8000"
INTERVALO_ENVIO = 10.0  # segundos entre leituras de batimento


def listar_onibus(url):
    """Consulta o cadastro de ônibus no servidor (GET /api/onibus)."""
    endereco = url.rstrip("/") + "/api/onibus"
    try:
        with urllib.request.urlopen(endereco, timeout=5) as resposta:
            dados = json.load(resposta)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as erro:
        raise ConnectionError(
            f"não foi possível consultar {endereco}: {erro}"
        ) from erro

    return dados.get("onibus") or []


def selecionar_onibus(url, nome=None):
    """Escolhe um ônibus do cadastro do servidor.

    Com `nome`, valida que ele está cadastrado. Sem `nome`, mostra a lista e
    pede a escolha pelo número ou pelo nome.
    """
    lista = listar_onibus(url)
    if not lista:
        raise SystemExit(
            "Nenhum ônibus cadastrado. Cadastre um no dashboard "
            f"({url.rstrip('/')}/) ou via "
            'POST /api/onibus {"nome": "onibus-01", "linha": "101"}.'
        )

    if nome:
        for item in lista:
            if item["onibus"] == nome:
                return item
        disponiveis = ", ".join(item["onibus"] for item in lista)
        raise SystemExit(
            f"Ônibus '{nome}' não está cadastrado. Disponíveis: {disponiveis}."
        )

    print("Ônibus cadastrados:")
    for indice, item in enumerate(lista, start=1):
        linha = f" — {item['linha']}" if item.get("linha") else ""
        estado = "desconectado" if item.get("obsoleto") else "conectado"
        print(f"  {indice}) {item['onibus']}{linha} · {estado}")

    while True:
        try:
            escolha = input("Selecione o ônibus deste computador: ").strip()
        except (EOFError, KeyboardInterrupt):
            raise SystemExit("\nSeleção cancelada.") from None

        if not escolha:
            continue

        if escolha.isdigit():
            indice = int(escolha)
            if 1 <= indice <= len(lista):
                return lista[indice - 1]

        for item in lista:
            if item["onibus"] == escolha:
                return item

        print("Opção inválida. Digite o número ou o nome exato do ônibus.")


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


def desenhar_painel(frame, passageiros, parado, portas_abertas, classificacao):
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
        f"Passageiros: {passageiros}/{classificacao['capacidade']}"
        f" ({classificacao['percentual']}%)",
        (20, 75),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (0, 255, 0),
        2
    )

    rotulo = classificacao["rotulo"]
    if superlotacao.em_alerta(classificacao["nivel"]):
        rotulo += " !!"

    cv2.putText(
        frame,
        f"Lotacao: {rotulo}",
        (20, 115),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        superlotacao.CORES_BGR[classificacao["nivel"]],
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
    analisador = argparse.ArgumentParser(
        description="Simulação de ônibus com contagem de passageiros."
    )
    analisador.add_argument(
        "--onibus",
        help="nome de um ônibus já cadastrado (pula a seleção interativa)",
    )
    analisador.add_argument(
        "--servidor",
        default=URL_SERVIDOR,
        help=f"URL do servidor/dashboard (padrão: {URL_SERVIDOR})",
    )
    argumentos = analisador.parse_args()

    try:
        escolhido = selecionar_onibus(argumentos.servidor, argumentos.onibus)
    except ConnectionError as erro:
        raise SystemExit(
            "Servidor indisponível. Inicie `.venv/bin/python servidor.py` "
            f"antes do busScript.\nDetalhe: {erro}"
        ) from erro

    id_onibus = escolhido["onibus"]
    linha = escolhido.get("linha") or ""
    print(
        f"Ônibus selecionado: {id_onibus}"
        + (f" — {linha}" if linha else "")
    )

    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        print("Erro: não foi possível abrir a câmera.")
        return

    detector = DetectorPassageiros(lado_entrada=SENTIDO_ENTRADA)
    cliente = ClienteLotacao(argumentos.servidor, id_onibus)
    viagem = datetime.now().strftime("%Y%m%d-%H%M%S")

    passageiros = PASSAGEIROS_INICIAIS
    parado = False
    portas_abertas = False
    alerta_anterior = None
    assinatura_enviada = None
    ultimo_envio = 0.0
    pico = passageiros

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

        classificacao = superlotacao.classificar(passageiros, LIMITE)
        nivel = classificacao["nivel"]
        pico = max(pico, passageiros)

        if superlotacao.em_alerta(nivel) and nivel != alerta_anterior:
            print(
                f"Alerta: {classificacao['rotulo']} - "
                f"{passageiros}/{LIMITE} ({classificacao['percentual']}%)"
            )
        alerta_anterior = nivel

        # Publica a cada mudança e também como batimento enquanto o app roda
        agora = time.monotonic()
        assinatura = (nivel, passageiros)
        if assinatura != assinatura_enviada or agora - ultimo_envio >= INTERVALO_ENVIO:
            cliente.enviar(passageiros, LIMITE, viagem=viagem, linha=linha)
            assinatura_enviada = assinatura
            ultimo_envio = agora

        desenhar_painel(
            annotated, passageiros, parado, portas_abertas, classificacao
        )

        cv2.imshow("Simulacao Onibus", annotated)

    cap.release()
    cv2.destroyAllWindows()
    cliente.fechar()

    print("\n--- RESUMO DA VIAGEM ---")
    print(f"Entradas: {detector.entradas}")
    print(f"Saídas: {detector.saidas}")
    print(f"Passageiros no ônibus: {passageiros}")
    print(f"Pico de passageiros: {pico}/{LIMITE}")
    print(f"Leituras enviadas: {cliente.enviados} | falhas: {cliente.falhas}")


if __name__ == "__main__":
    main()
