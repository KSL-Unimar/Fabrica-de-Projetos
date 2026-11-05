# CLASSIFICAÇÃO DE SUPERLOTAÇÃO
#
# Converte a contagem de passageiros do busScript.py em um nível de lotação.
# A capacidade (LIMITE do busScript.py) é a referência: 100% = capacidade cheia.

NORMAL = "normal"
ATENCAO = "atencao"
LOTADO = "lotado"
SUPERLOTADO = "superlotado"

NIVEIS = (NORMAL, ATENCAO, LOTADO, SUPERLOTADO)
NIVEIS_ALERTA = (LOTADO, SUPERLOTADO)

ROTULOS = {
    NORMAL: "NORMAL",
    ATENCAO: "ATENÇÃO",
    LOTADO: "LOTADO",
    SUPERLOTADO: "SUPERLOTADO",
}

# Cores BGR para o painel do OpenCV
CORES_BGR = {
    NORMAL: (0, 200, 0),
    ATENCAO: (0, 215, 255),
    LOTADO: (0, 140, 255),
    SUPERLOTADO: (0, 0, 255),
}

# Limiares como fração da capacidade (1.0 = capacidade cheia)
LIMIAR_ATENCAO = 0.70
LIMIAR_LOTADO = 1.00
LIMIAR_SUPERLOTADO = 1.20


def classificar(
    passageiros,
    capacidade,
    limiar_atencao=LIMIAR_ATENCAO,
    limiar_lotado=LIMIAR_LOTADO,
    limiar_superlotado=LIMIAR_SUPERLOTADO,
):
    """Classifica a lotação e devolve nível, rótulo, contagem e percentual."""
    capacidade = int(capacidade)
    if capacidade <= 0:
        raise ValueError("capacidade deve ser maior que zero")

    passageiros = max(0, int(passageiros))
    fracao = passageiros / capacidade
    percentual = round(fracao * 100, 1)

    if fracao >= limiar_superlotado:
        nivel = SUPERLOTADO
    elif fracao >= limiar_lotado:
        nivel = LOTADO
    elif fracao >= limiar_atencao:
        nivel = ATENCAO
    else:
        nivel = NORMAL

    return {
        "nivel": nivel,
        "rotulo": ROTULOS[nivel],
        "passageiros": passageiros,
        "capacidade": capacidade,
        "percentual": percentual,
    }


def em_alerta(nivel):
    """True para LOTADO/SUPERLOTADO (a partir da capacidade)."""
    return nivel in NIVEIS_ALERTA
