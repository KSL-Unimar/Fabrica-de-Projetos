# SERVIDOR DE LOTAÇÃO (API + DASHBOARD + SQLITE)
#
# Recebe as leituras enviadas pelo busScript.py (cliente_api.py), classifica a
# superlotação com superlotacao.py e guarda tudo em SQLite. O dashboard em
# home.html consome a API e mostra o alerta atual + histórico do dia.
#
# Uso:
#   .venv/bin/python servidor.py
#   .venv/bin/python servidor.py --host 0.0.0.0 --porta 8000
#
# Endpoints:
#   POST   /api/leituras      {"onibus", "passageiros", "capacidade", "viagem", "linha"}
#   GET    /api/estado        última leitura + alerta atual
#   GET    /api/historico     ?onibus=&data=YYYY-MM-DD
#   GET    /api/onibus        ônibus cadastrados (+ status/estatísticas)
#   POST   /api/onibus        {"nome", "linha"} cadastra um ônibus
#   PUT    /api/onibus/<nome> altera nome e/ou linha
#   DELETE /api/onibus/<nome> remove do cadastro (mantém o histórico)
#   GET    /                  dashboard (home.html)
#   GET    /onibus            gerenciamento de ônibus (onibus.html)
#   GET    /estilo.css        folha de estilo compartilhada

import argparse
import json
import math
import re
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import superlotacao

BASE = Path(__file__).resolve().parent
BANCO_PADRAO = BASE / "dados" / "onibus.db"
DASHBOARD = BASE / "home.html"
PAGINA_ONIBUS = BASE / "onibus.html"
ESTILO = BASE / "estilo.css"

HOST_PADRAO = "127.0.0.1"
PORTA_PADRAO = 8000

# Segundos sem leitura antes de considerar o ônibus "desconectado"
LIMITE_OBSOLETO = 60

# Quantidade máxima de pontos devolvidos para o gráfico e para a tabela
MAX_PONTOS_SERIE = 240
MAX_LEITURAS_TABELA = 100

DATA_VALIDA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OnibusDuplicado(ValueError):
    """Nome de ônibus já cadastrado."""


class OnibusNaoEncontrado(ValueError):
    """Ônibus ausente no cadastro."""


# Sentinela para diferenciar "corpo inválido" de um JSON válido que seja null
_CORPO_INVALIDO = object()


ESQUEMA = """
CREATE TABLE IF NOT EXISTS onibus (
    nome TEXT PRIMARY KEY,
    linha TEXT NOT NULL DEFAULT '',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leituras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    data TEXT NOT NULL,
    hora TEXT NOT NULL,
    onibus TEXT NOT NULL,
    viagem TEXT NOT NULL DEFAULT '',
    linha TEXT NOT NULL DEFAULT '',
    passageiros INTEGER NOT NULL,
    capacidade INTEGER NOT NULL,
    percentual REAL NOT NULL,
    nivel TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leituras_onibus_data
    ON leituras (onibus, data);
"""


def conectar(banco):
    conexao = sqlite3.connect(banco, timeout=5)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA journal_mode=WAL")
    conexao.execute("PRAGMA synchronous=NORMAL")
    return conexao


def iniciar_banco(banco):
    banco.parent.mkdir(parents=True, exist_ok=True)
    with conectar(banco) as conexao:
        cadastro_existia = conexao.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='onibus'"
        ).fetchone() is not None

        conexao.executescript(ESQUEMA)

        # Bancos criados antes do campo "linha" precisam da coluna nova
        colunas = {
            coluna["name"]
            for coluna in conexao.execute("PRAGMA table_info(leituras)")
        }
        if "linha" not in colunas:
            conexao.execute(
                "ALTER TABLE leituras ADD COLUMN linha TEXT NOT NULL DEFAULT ''"
            )

        # Primeira execução com banco antigo: importa para o cadastro os
        # ônibus que já aparecem nas leituras. Roda só quando a tabela é criada.
        if not cadastro_existia:
            agora = datetime.now().isoformat(timespec="seconds")
            conexao.execute(
                """
                INSERT OR IGNORE INTO onibus
                    (nome, linha, criado_em, atualizado_em)
                SELECT onibus, COALESCE(MAX(NULLIF(linha, '')), ''), ?, ?
                FROM leituras
                GROUP BY onibus
                """,
                (agora, agora),
            )


def registrar_leitura(conexao, dados):
    """Valida, classifica e grava uma leitura. Levanta ValueError se inválida."""
    if not isinstance(dados, dict):
        raise ValueError("corpo deve ser um objeto JSON")

    onibus = str(dados.get("onibus") or "").strip()
    if not onibus:
        raise ValueError("'onibus' é obrigatório")

    try:
        passageiros = int(dados["passageiros"])
        capacidade = int(dados["capacidade"])
    except KeyError as erro:
        raise ValueError(f"campo obrigatório ausente: {erro.args[0]}") from erro
    except (TypeError, ValueError) as erro:
        raise ValueError("'passageiros' e 'capacidade' devem ser inteiros") from erro

    viagem = str(dados.get("viagem") or "")
    linha = str(dados.get("linha") or "").strip()

    # O servidor é a fonte da verdade da classificação
    classificacao = superlotacao.classificar(passageiros, capacidade)
    agora = datetime.now()
    criado_em = agora.isoformat(timespec="seconds")

    # Compatibilidade: um cliente antigo que ainda não foi cadastrado entra
    # automaticamente no cadastro, sem sobrescrever a linha já registrada.
    conexao.execute(
        """
        INSERT OR IGNORE INTO onibus
            (nome, linha, criado_em, atualizado_em)
        VALUES (?, ?, ?, ?)
        """,
        (onibus, linha, criado_em, criado_em),
    )

    registro = {
        "criado_em": criado_em,
        "data": agora.strftime("%Y-%m-%d"),
        "hora": agora.strftime("%H:%M:%S"),
        "onibus": onibus,
        "viagem": viagem,
        "linha": linha,
        **classificacao,
    }

    cursor = conexao.execute(
        """
        INSERT INTO leituras
            (criado_em, data, hora, onibus, viagem, linha,
             passageiros, capacidade, percentual, nivel)
        VALUES
            (:criado_em, :data, :hora, :onibus, :viagem, :linha,
             :passageiros, :capacidade, :percentual, :nivel)
        """,
        registro,
    )
    conexao.commit()

    registro["id"] = cursor.lastrowid
    return registro


def buscar_onibus(conexao):
    linhas = conexao.execute(
        """
        SELECT o.nome AS onibus,
               o.linha AS linha,
               MAX(l.criado_em) AS ultima_leitura,
               COUNT(l.id) AS leituras,
               GROUP_CONCAT(DISTINCT NULLIF(l.linha, '')) AS linhas
        FROM onibus o
        LEFT JOIN leituras l ON l.onibus = o.nome
        GROUP BY o.nome
        ORDER BY ultima_leitura DESC, o.nome
        """
    ).fetchall()

    agora = datetime.now()
    onibus = []
    for linha in linhas:
        item = dict(linha)
        item["linha"] = item["linha"] or ""
        item["linhas"] = item["linha"] or item["linhas"] or ""

        if item["ultima_leitura"] is None:
            item["idade_segundos"] = None
            item["obsoleto"] = True
        else:
            ultima = datetime.fromisoformat(item["ultima_leitura"])
            item["idade_segundos"] = max(
                0, round((agora - ultima).total_seconds())
            )
            item["obsoleto"] = item["idade_segundos"] > LIMITE_OBSOLETO

        onibus.append(item)

    return onibus


def cadastrar_onibus(conexao, dados):
    """Cadastra um ônibus. Levanta ValueError se os dados forem inválidos."""
    if not isinstance(dados, dict):
        raise ValueError("corpo deve ser um objeto JSON")

    nome = str(dados.get("nome") or "").strip()
    if not nome:
        raise ValueError("'nome' é obrigatório")

    linha = str(dados.get("linha") or "").strip()
    agora = datetime.now().isoformat(timespec="seconds")

    try:
        conexao.execute(
            """
            INSERT INTO onibus (nome, linha, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?)
            """,
            (nome, linha, agora, agora),
        )
        conexao.commit()
    except sqlite3.IntegrityError as erro:
        raise OnibusDuplicado("ônibus já cadastrado") from erro

    return {
        "onibus": nome,
        "linha": linha,
        "criado_em": agora,
        "atualizado_em": agora,
    }


def atualizar_onibus(conexao, nome_atual, dados):
    """Altera nome e/ou linha. Renomear também atualiza as leituras antigas."""
    if not isinstance(dados, dict):
        raise ValueError("corpo deve ser um objeto JSON")

    atual = conexao.execute(
        "SELECT nome, linha, criado_em FROM onibus WHERE nome = ?",
        (nome_atual,),
    ).fetchone()
    if atual is None:
        raise OnibusNaoEncontrado("ônibus não encontrado")

    novo_nome = str(dados.get("nome") or nome_atual).strip()
    if not novo_nome:
        raise ValueError("'nome' não pode ficar vazio")

    if "linha" in dados:
        linha = str(dados.get("linha") or "").strip()
    else:
        linha = atual["linha"]

    agora = datetime.now().isoformat(timespec="seconds")

    try:
        if novo_nome != nome_atual:
            conexao.execute(
                "UPDATE leituras SET onibus = ? WHERE onibus = ?",
                (novo_nome, nome_atual),
            )
        conexao.execute(
            """
            UPDATE onibus
            SET nome = ?, linha = ?, atualizado_em = ?
            WHERE nome = ?
            """,
            (novo_nome, linha, agora, nome_atual),
        )
        conexao.commit()
    except sqlite3.IntegrityError as erro:
        conexao.rollback()
        raise OnibusDuplicado("já existe um ônibus com esse nome") from erro

    return {
        "onibus": novo_nome,
        "linha": linha,
        "criado_em": atual["criado_em"],
        "atualizado_em": agora,
    }


def excluir_onibus(conexao, nome):
    """Remove o cadastro; as leituras históricas são preservadas."""
    cursor = conexao.execute("DELETE FROM onibus WHERE nome = ?", (nome,))
    if cursor.rowcount == 0:
        raise OnibusNaoEncontrado("ônibus não encontrado")

    conexao.commit()
    return {"removido": True, "onibus": nome}


def buscar_estado(conexao, onibus=None):
    if not onibus:
        onibus = _onibus_padrao(conexao, None)
    if onibus is None:
        return {"vazio": True, "onibus": None}

    linha = conexao.execute(
        "SELECT * FROM leituras WHERE onibus = ? ORDER BY id DESC LIMIT 1",
        (onibus,),
    ).fetchone()

    if linha is None:
        return {"vazio": True, "onibus": onibus}

    estado = dict(linha)
    idade = datetime.now() - datetime.fromisoformat(estado["criado_em"])
    estado["idade_segundos"] = max(0, round(idade.total_seconds()))
    estado["obsoleto"] = estado["idade_segundos"] > LIMITE_OBSOLETO
    estado["em_alerta"] = superlotacao.em_alerta(estado["nivel"])
    return estado


def _amostrar(leituras, maximo):
    """Reduz a série mantendo o pico de cada bloco (ordem cronológica)."""
    if len(leituras) <= maximo:
        return leituras

    tamanho = math.ceil(len(leituras) / maximo)
    amostra = []
    for inicio in range(0, len(leituras), tamanho):
        bloco = leituras[inicio:inicio + tamanho]
        amostra.append(max(bloco, key=lambda leitura: leitura["percentual"]))
    return amostra


def _extrair_alertas(leituras):
    """Transições que entraram em LOTADO/SUPERLOTADO (ordem cronológica)."""
    alertas = []
    anterior = None
    for leitura in leituras:
        nivel = leitura["nivel"]
        if nivel != anterior and superlotacao.em_alerta(nivel):
            alertas.append(
                {
                    "hora": leitura["hora"],
                    "onibus": leitura["onibus"],
                    "linha": leitura["linha"],
                    "nivel": nivel,
                    "rotulo": superlotacao.ROTULOS[nivel],
                    "passageiros": leitura["passageiros"],
                    "capacidade": leitura["capacidade"],
                    "percentual": leitura["percentual"],
                }
            )
        anterior = nivel
    return alertas


def _resumo(leituras):
    pico = max(leituras, key=lambda leitura: leitura["passageiros"])
    ultima = leituras[-1]
    return {
        "total_leituras": len(leituras),
        "onibus": ultima["onibus"],
        "linha": ultima.get("linha", ""),
        "capacidade": ultima["capacidade"],
        "atual": ultima["passageiros"],
        "atual_nivel": ultima["nivel"],
        "pico": pico["passageiros"],
        "pico_percentual": pico["percentual"],
        "pico_nivel": pico["nivel"],
        "pico_hora": pico["hora"],
        "media_percentual": round(
            sum(leitura["percentual"] for leitura in leituras) / len(leituras), 1
        ),
        "leituras_em_alerta": sum(
            1 for leitura in leituras if superlotacao.em_alerta(leitura["nivel"])
        ),
    }


def buscar_historico(conexao, onibus, data):
    linhas = conexao.execute(
        """
        SELECT criado_em, data, hora, onibus, viagem, linha,
               passageiros, capacidade, percentual, nivel
        FROM leituras
        WHERE onibus = ? AND data = ?
        ORDER BY criado_em, id
        """,
        (onibus, data),
    ).fetchall()
    leituras = [dict(linha) for linha in linhas]

    if not leituras:
        return {
            "onibus": onibus,
            "data": data,
            "vazio": True,
            "resumo": None,
            "serie": [],
            "alertas": [],
            "leituras": [],
        }

    return {
        "onibus": onibus,
        "data": data,
        "vazio": False,
        "resumo": _resumo(leituras),
        "serie": _amostrar(leituras, MAX_PONTOS_SERIE),
        "alertas": _extrair_alertas(leituras),
        "leituras": leituras[-MAX_LEITURAS_TABELA:],
    }


def _onibus_padrao(conexao, onibus):
    if onibus:
        return onibus

    # Sem ônibus explícito, usa o cadastrado com leitura mais recente.
    # Leituras de ônibus removidos do cadastro não voltam como padrão.
    linha = conexao.execute(
        """
        SELECT o.nome
        FROM onibus o
        LEFT JOIN leituras l ON l.onibus = o.nome
        GROUP BY o.nome
        ORDER BY MAX(l.criado_em) DESC, o.nome
        LIMIT 1
        """
    ).fetchone()
    return linha["nome"] if linha else None


class Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, endereco, banco, verboso=False):
        super().__init__(endereco, Manipulador)
        self.banco = banco
        self.verboso = verboso


class Manipulador(BaseHTTPRequestHandler):
    server_version = "ServidorLotacao/1.0"

    # ---------- respostas ----------

    def _json(self, dados, status=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _erro(self, mensagem, status=400):
        self._json({"erro": mensagem}, status=status)

    def _arquivo(self, caminho, tipo, rotulo):
        """Serve um arquivo estático do projeto (HTML/CSS)."""
        try:
            corpo = caminho.read_bytes()
        except FileNotFoundError:
            self._erro(f"{rotulo} não encontrado", status=500)
            return
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _dashboard(self):
        self._arquivo(DASHBOARD, "text/html; charset=utf-8", "home.html")

    def _pagina_onibus(self):
        self._arquivo(PAGINA_ONIBUS, "text/html; charset=utf-8", "onibus.html")

    def _estilo(self):
        self._arquivo(ESTILO, "text/css; charset=utf-8", "estilo.css")

    def _consultas(self):
        return parse_qs(urlparse(self.path).query)

    def _conexao(self):
        return conectar(self.server.banco)

    def _ler_json(self):
        """Lê o corpo JSON da requisição.

        Devolve o valor decodificado ou ``_CORPO_INVALIDO`` depois de já ter
        respondido com o erro apropriado.
        """
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._erro("Content-Length inválido")
            return _CORPO_INVALIDO

        if tamanho <= 0:
            self._erro("corpo vazio")
            return _CORPO_INVALIDO
        if tamanho > 1_000_000:
            self._erro("corpo muito grande", status=413)
            return _CORPO_INVALIDO

        try:
            return json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._erro("JSON inválido")
            return _CORPO_INVALIDO

    def _nome_onibus(self):
        """Extrai o nome de /api/onibus/<nome> (URL-decoded) ou responde 404."""
        caminho = urlparse(self.path).path
        if not caminho.startswith("/api/onibus/"):
            return None
        nome = unquote(caminho[len("/api/onibus/"):]).strip()
        if not nome:
            return None
        return nome

    # ---------- rotas ----------

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"
        )
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        caminho = urlparse(self.path).path
        consultas = self._consultas()

        if caminho in ("/", "/home.html", "/index.html"):
            self._dashboard()
            return

        if caminho in ("/onibus", "/onibus.html"):
            self._pagina_onibus()
            return

        if caminho == "/estilo.css":
            self._estilo()
            return

        if caminho == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        try:
            if caminho == "/api/saude":
                self._json(
                    {
                        "ok": True,
                        "hora": datetime.now().isoformat(timespec="seconds"),
                        "banco": str(self.server.banco),
                    }
                )
                return

            with self._conexao() as conexao:
                if caminho == "/api/onibus":
                    self._json({"onibus": buscar_onibus(conexao)})
                    return

                if caminho == "/api/estado":
                    onibus = (consultas.get("onibus") or [None])[0]
                    self._json(buscar_estado(conexao, onibus))
                    return

                if caminho == "/api/historico":
                    data = (consultas.get("data") or [None])[0]
                    if data is None:
                        data = datetime.now().strftime("%Y-%m-%d")
                    elif not DATA_VALIDA.match(data):
                        self._erro("data deve estar no formato YYYY-MM-DD")
                        return

                    onibus = _onibus_padrao(
                        conexao, (consultas.get("onibus") or [None])[0]
                    )
                    if onibus is None:
                        self._json(
                            {
                                "onibus": None,
                                "data": data,
                                "vazio": True,
                                "resumo": None,
                                "serie": [],
                                "alertas": [],
                                "leituras": [],
                            }
                        )
                        return

                    self._json(buscar_historico(conexao, onibus, data))
                    return

            self._erro("rota não encontrada", status=404)
        except sqlite3.Error as erro:
            self._erro(f"erro no banco: {erro}", status=500)

    def do_POST(self):
        caminho = urlparse(self.path).path

        if caminho not in ("/api/leituras", "/api/onibus"):
            self._erro("rota não encontrada", status=404)
            return

        dados = self._ler_json()
        if dados is _CORPO_INVALIDO:
            return

        try:
            with self._conexao() as conexao:
                if caminho == "/api/onibus":
                    registro = cadastrar_onibus(conexao, dados)
                else:
                    registro = registrar_leitura(conexao, dados)
        except OnibusDuplicado as erro:
            self._erro(str(erro), status=409)
            return
        except ValueError as erro:
            self._erro(str(erro))
            return
        except sqlite3.Error as erro:
            self._erro(f"erro no banco: {erro}", status=500)
            return

        self._json(registro, status=201)

    def do_PUT(self):
        nome = self._nome_onibus()
        if nome is None:
            self._erro("rota não encontrada", status=404)
            return

        dados = self._ler_json()
        if dados is _CORPO_INVALIDO:
            return

        try:
            with self._conexao() as conexao:
                registro = atualizar_onibus(conexao, nome, dados)
        except OnibusNaoEncontrado as erro:
            self._erro(str(erro), status=404)
            return
        except OnibusDuplicado as erro:
            self._erro(str(erro), status=409)
            return
        except ValueError as erro:
            self._erro(str(erro))
            return
        except sqlite3.Error as erro:
            self._erro(f"erro no banco: {erro}", status=500)
            return

        self._json(registro)

    def do_DELETE(self):
        nome = self._nome_onibus()
        if nome is None:
            self._erro("rota não encontrada", status=404)
            return

        try:
            with self._conexao() as conexao:
                registro = excluir_onibus(conexao, nome)
        except OnibusNaoEncontrado as erro:
            self._erro(str(erro), status=404)
            return
        except ValueError as erro:
            self._erro(str(erro))
            return
        except sqlite3.Error as erro:
            self._erro(f"erro no banco: {erro}", status=500)
            return

        self._json(registro)

    def log_message(self, formato, *argumentos):
        if getattr(self.server, "verboso", False):
            super().log_message(formato, *argumentos)


def main():
    analisador = argparse.ArgumentParser(
        description="Servidor da lotação do ônibus (API + dashboard + SQLite)."
    )
    analisador.add_argument("--host", default=HOST_PADRAO)
    analisador.add_argument("--porta", type=int, default=PORTA_PADRAO)
    analisador.add_argument("--banco", type=Path, default=BANCO_PADRAO)
    analisador.add_argument(
        "--verboso", action="store_true", help="mostra cada requisição no terminal"
    )
    argumentos = analisador.parse_args()

    iniciar_banco(argumentos.banco)
    servidor = Servidor(
        (argumentos.host, argumentos.porta), argumentos.banco, argumentos.verboso
    )

    print(f"Banco:     {argumentos.banco}")
    print(f"Dashboard: http://{argumentos.host}:{argumentos.porta}/")
    print("Ctrl+C para encerrar.")

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
