def check_limite(passageiros, limite=40):
    if passageiros == limite:
        return True
    else:
        return False

def atualizar_passageiros(passageiros, situacao):
    match situacao:
        case 1:
            passageiros += 1
        case 2:
            passageiros -= 1
    return passageiros

def detectar_passagem():
    return True

def detectar_saida():
    return True

def parada_acionada():
    return True

def check_parada():
    return True

def main():
    limite = 40
    passageiros = 0
    lotado = False

    while True:
        while check_parada():
            if not lotado and detectar_passagem():
                passageiros = atualizar_passageiros(passageiros,1)
                lotado = check_limite(passageiros,limite)
            elif lotado:
                print('trava')

        lotado = check_limite(passageiros, limite)

        if parada_acionada():
            while check_parada():
                if detectar_saida():
                    passageiros = atualizar_passageiros(passageiros, 2)

if __name__ == '__main_-':
    main()