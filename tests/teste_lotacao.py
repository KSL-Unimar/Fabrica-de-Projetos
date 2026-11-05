# TESTE DA CLASSIFICAÇÃO E DA API DE LOTAÇÃO
#
# Roda sem câmera e sem GUI: usa um banco SQLite temporário e um servidor
# HTTP local em porta aleatória.
#
# Uso: .venv/bin/python tests/teste_lotacao.py

import json
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import servidor
import superlotacao
from cliente_api import ClienteLotacao


def _enviar(base, metodo, caminho, dados=None):
    corpo = None if dados is None else json.dumps(dados).encode("utf-8")
    requisicao = urllib.request.Request(
        base + caminho,
        data=corpo,
        method=metodo,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(requisicao, timeout=5) as resposta:
        return resposta.status, json.load(resposta)


def _post(base, dados):
    return _enviar(base, "POST", "/api/leituras", dados)


def _get(base, caminho):
    with urllib.request.urlopen(base + caminho, timeout=5) as resposta:
        return resposta.read(), resposta.headers.get("Content-Type", "")


def _esperar(condicao, timeout=3.0):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicao():
            return True
        time.sleep(0.05)
    return False


def testar_classificacao():
    casos = [
        (0, "normal"),
        (27, "normal"),
        (28, "atencao"),
        (39, "atencao"),
        (40, "lotado"),
        (47, "lotado"),
        (48, "superlotado"),
        (100, "superlotado"),
    ]
    for passageiros, esperado in casos:
        resultado = superlotacao.classificar(passageiros, 40)
        assert resultado["nivel"] == esperado, (passageiros, resultado)
        assert resultado["capacidade"] == 40
        assert resultado["percentual"] == round(passageiros / 40 * 100, 1)

    assert not superlotacao.em_alerta("atencao")
    assert superlotacao.em_alerta("lotado")
    assert superlotacao.em_alerta("superlotado")

    try:
        superlotacao.classificar(0, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("capacidade zero deveria levantar ValueError")


def testar_api():
    with tempfile.TemporaryDirectory() as pasta:
        banco = Path(pasta) / "teste.db"
        servidor.iniciar_banco(banco)

        srv = servidor.Servidor(("127.0.0.1", 0), banco)
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()

        try:
            for passageiros in (10, 35, 42, 50):
                status, _ = _post(
                    base,
                    {
                        "onibus": "teste",
                        "passageiros": passageiros,
                        "capacidade": 40,
                        "viagem": "viagem-teste",
                        "linha": "101",
                    },
                )
                assert status == 201, status

            corpo, _ = _get(base, "/api/estado?onibus=teste")
            estado = json.loads(corpo)
            assert estado["passageiros"] == 50, estado
            assert estado["nivel"] == "superlotado", estado
            assert estado["percentual"] == 125.0, estado
            assert estado["linha"] == "101", estado
            assert estado["em_alerta"] is True
            assert estado["obsoleto"] is False

            data = datetime.now().strftime("%Y-%m-%d")
            corpo, _ = _get(base, f"/api/historico?onibus=teste&data={data}")
            historico = json.loads(corpo)
            assert historico["vazio"] is False
            assert historico["resumo"]["pico"] == 50
            assert historico["resumo"]["capacidade"] == 40
            assert historico["resumo"]["pico_nivel"] == "superlotado"
            assert historico["resumo"]["linha"] == "101"
            assert len(historico["serie"]) == 4
            assert [alerta["nivel"] for alerta in historico["alertas"]] == [
                "lotado",
                "superlotado",
            ]
            assert [alerta["linha"] for alerta in historico["alertas"]] == [
                "101",
                "101",
            ]
            assert len(historico["leituras"]) == 4
            assert {leitura["onibus"] for leitura in historico["leituras"]} == {
                "teste"
            }
            assert {leitura["linha"] for leitura in historico["leituras"]} == {
                "101"
            }

            corpo, tipo = _get(base, "/")
            dashboard = corpo.decode("utf-8")
            assert "BUS CHECK" in dashboard
            assert "Ônibus" in dashboard
            assert "Linha" in dashboard
            assert 'href="/onibus"' in dashboard
            assert 'href="/estilo.css"' in dashboard
            assert 'id="form-onibus"' not in dashboard
            assert "text/html" in tipo

            corpo, tipo = _get(base, "/onibus")
            pagina = corpo.decode("utf-8")
            assert "Gerenciar ônibus" in pagina
            assert 'id="form-onibus"' in pagina
            assert 'id="lista-onibus"' in pagina
            assert 'href="/estilo.css"' in pagina
            assert 'href="/"' in pagina
            assert "text/html" in tipo

            corpo, tipo = _get(base, "/estilo.css")
            estilo = corpo.decode("utf-8")
            assert "--fundo" in estilo
            assert "overscroll-behavior-y" in estilo
            assert "text/css" in tipo

            corpo, _ = _get(base, "/api/onibus")
            onibus = json.loads(corpo)["onibus"]
            assert [item["onibus"] for item in onibus] == ["teste"]
            assert onibus[0]["leituras"] == 4
            assert onibus[0]["linhas"] == "101"
            assert onibus[0]["obsoleto"] is False
            assert onibus[0]["idade_segundos"] >= 0

            for invalido in (
                {"onibus": "teste", "passageiros": 1, "capacidade": 0},
                {"passageiros": 1, "capacidade": 40},
            ):
                try:
                    _post(base, invalido)
                except urllib.error.HTTPError as erro:
                    assert erro.code == 400, (invalido, erro.code)
                else:
                    raise AssertionError(f"deveria rejeitar {invalido}")

            cliente = ClienteLotacao(base, "teste-cliente")
            cliente.enviar(33, 40, viagem="viagem-cliente", linha="202")
            cliente.fechar()

            assert _esperar(
                lambda: json.loads(_get(base, "/api/estado?onibus=teste-cliente")[0])[
                    "passageiros"
                ]
                == 33
            ), "cliente_api não publicou a leitura"
            estado_cliente = json.loads(
                _get(base, "/api/estado?onibus=teste-cliente")[0]
            )
            assert estado_cliente["linha"] == "202", estado_cliente
            assert cliente.enviados == 1, cliente.enviados
            assert cliente.falhas == 0, cliente.falhas
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(timeout=2)


def testar_migracao():
    with tempfile.TemporaryDirectory() as pasta:
        banco = Path(pasta) / "antigo.db"
        with sqlite3.connect(banco) as conexao:
            conexao.executescript(
                """
                CREATE TABLE leituras (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    criado_em TEXT NOT NULL,
                    data TEXT NOT NULL,
                    hora TEXT NOT NULL,
                    onibus TEXT NOT NULL,
                    viagem TEXT NOT NULL DEFAULT '',
                    passageiros INTEGER NOT NULL,
                    capacidade INTEGER NOT NULL,
                    percentual REAL NOT NULL,
                    nivel TEXT NOT NULL
                );
                INSERT INTO leituras
                    (criado_em, data, hora, onibus, viagem,
                     passageiros, capacidade, percentual, nivel)
                VALUES
                    ('2026-01-01T10:00:00', '2026-01-01', '10:00:00', 'antigo', '',
                     10, 40, 25.0, 'normal');
                """
            )

        servidor.iniciar_banco(banco)

        with sqlite3.connect(banco) as conexao:
            colunas = [
                linha[1]
                for linha in conexao.execute("PRAGMA table_info(leituras)")
            ]
            assert "linha" in colunas, colunas
            linha = conexao.execute("SELECT linha FROM leituras").fetchone()
            assert linha[0] == "", linha

            cadastro = conexao.execute(
                "SELECT nome, linha FROM onibus ORDER BY nome"
            ).fetchall()
            assert cadastro == [("antigo", "")], cadastro

        # Rodar de novo não deve recriar/duplicar o cadastro
        with sqlite3.connect(banco) as conexao:
            conexao.execute("DELETE FROM onibus")
        servidor.iniciar_banco(banco)
        with sqlite3.connect(banco) as conexao:
            assert conexao.execute("SELECT COUNT(*) FROM onibus").fetchone()[0] == 0


def testar_status_onibus():
    with tempfile.TemporaryDirectory() as pasta:
        banco = Path(pasta) / "status.db"
        servidor.iniciar_banco(banco)

        with servidor.conectar(banco) as conexao:
            servidor.registrar_leitura(
                conexao,
                {"onibus": "recente", "passageiros": 10, "capacidade": 40},
            )

            # cadastro do ônibus "antigo" (o INSERT abaixo é direto nas leituras)
            conexao.execute(
                """
                INSERT OR IGNORE INTO onibus
                    (nome, linha, criado_em, atualizado_em)
                VALUES (?, ?, ?, ?)
                """,
                ("antigo", "", datetime.now().isoformat(timespec="seconds"),
                 datetime.now().isoformat(timespec="seconds")),
            )

            antigo = datetime.now() - timedelta(
                seconds=servidor.LIMITE_OBSOLETO + 1
            )
            conexao.execute(
                """
                INSERT INTO leituras
                    (criado_em, data, hora, onibus, viagem, linha,
                     passageiros, capacidade, percentual, nivel)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    antigo.isoformat(timespec="seconds"),
                    antigo.strftime("%Y-%m-%d"),
                    antigo.strftime("%H:%M:%S"),
                    "antigo",
                    "",
                    "",
                    10,
                    40,
                    25.0,
                    "normal",
                ),
            )
            conexao.commit()

        with servidor.conectar(banco) as conexao:
            status = {
                item["onibus"]: item
                for item in servidor.buscar_onibus(conexao)
            }

        assert status["recente"]["obsoleto"] is False, status["recente"]
        assert status["antigo"]["obsoleto"] is True, status["antigo"]
        assert (
            status["antigo"]["idade_segundos"] >= servidor.LIMITE_OBSOLETO
        ), status["antigo"]


def testar_cadastro():
    with tempfile.TemporaryDirectory() as pasta:
        banco = Path(pasta) / "cadastro.db"
        servidor.iniciar_banco(banco)

        srv = servidor.Servidor(("127.0.0.1", 0), banco)
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()

        def espera_erro(metodo, caminho, dados, codigo):
            try:
                _enviar(base, metodo, caminho, dados)
            except urllib.error.HTTPError as erro:
                assert erro.code == codigo, (caminho, erro.code)
            else:
                raise AssertionError(f"{metodo} {caminho} deveria dar {codigo}")

        try:
            corpo, _ = _get(base, "/api/onibus")
            assert json.loads(corpo)["onibus"] == []

            status, cadastrado = _enviar(
                base,
                "POST",
                "/api/onibus",
                {"nome": "onibus-a", "linha": "101"},
            )
            assert status == 201, status
            assert cadastrado["onibus"] == "onibus-a"
            assert cadastrado["linha"] == "101"

            espera_erro("POST", "/api/onibus", {"nome": "onibus-a"}, 409)
            espera_erro("POST", "/api/onibus", {"linha": "100"}, 400)
            espera_erro("PUT", "/api/onibus/nao-existe", {"linha": "1"}, 404)
            espera_erro("DELETE", "/api/onibus/nao-existe", None, 404)

            corpo, _ = _get(base, "/api/onibus")
            onibus = json.loads(corpo)["onibus"]
            assert [item["onibus"] for item in onibus] == ["onibus-a"]
            assert onibus[0]["leituras"] == 0
            assert onibus[0]["linha"] == "101"
            assert onibus[0]["obsoleto"] is True
            assert onibus[0]["idade_segundos"] is None

            _post(
                base,
                {
                    "onibus": "onibus-a",
                    "passageiros": 12,
                    "capacidade": 40,
                    "linha": "101",
                },
            )
            corpo, _ = _get(base, "/api/onibus")
            onibus = json.loads(corpo)["onibus"]
            assert onibus[0]["leituras"] == 1
            assert onibus[0]["obsoleto"] is False

            # Renomear (com espaço, para exercitar o unquote) e trocar a linha
            nome_antigo = urllib.parse.quote("onibus-a")
            status, alterado = _enviar(
                base,
                "PUT",
                f"/api/onibus/{nome_antigo}",
                {"nome": "onibus a", "linha": "202"},
            )
            assert status == 200, status
            assert alterado["onibus"] == "onibus a"
            assert alterado["linha"] == "202"

            nome_codificado = urllib.parse.quote("onibus a")

            corpo, _ = _get(base, "/api/onibus")
            onibus = json.loads(corpo)["onibus"]
            assert [item["onibus"] for item in onibus] == ["onibus a"]
            assert onibus[0]["linha"] == "202"
            assert onibus[0]["leituras"] == 1

            # Renomear não pode colidir com outro cadastro
            _enviar(base, "POST", "/api/onibus", {"nome": "onibus-b"})
            espera_erro("PUT", f"/api/onibus/{nome_codificado}",
                        {"nome": "onibus-b"}, 409)
            _enviar(base, "DELETE", "/api/onibus/onibus-b")

            data = datetime.now().strftime("%Y-%m-%d")
            corpo, _ = _get(
                base,
                f"/api/historico?onibus={nome_codificado}&data={data}",
            )
            historico = json.loads(corpo)
            assert historico["vazio"] is False
            assert {leitura["onibus"] for leitura in historico["leituras"]} == {
                "onibus a"
            }

            # Excluir remove do cadastro, mas preserva as leituras
            status, removido = _enviar(
                base, "DELETE", f"/api/onibus/{nome_codificado}"
            )
            assert status == 200, status
            assert removido["removido"] is True

            corpo, _ = _get(base, "/api/onibus")
            assert json.loads(corpo)["onibus"] == []

            corpo, _ = _get(
                base,
                f"/api/historico?onibus={nome_codificado}&data={data}",
            )
            assert json.loads(corpo)["vazio"] is False
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(timeout=2)


def main():
    testar_classificacao()
    print("ok  classificação por faixas de capacidade")

    testar_migracao()
    print("ok  migração de banco antigo (coluna linha + cadastro inicial)")

    testar_status_onibus()
    print("ok  status conectado/desconectado por ônibus")

    testar_cadastro()
    print("ok  cadastro de ônibus (criar, alterar, excluir, colisões)")

    testar_api()
    print("ok  API, banco, histórico, alertas e cliente de envio")

    print("\nTodos os testes passaram.")


if __name__ == "__main__":
    main()
