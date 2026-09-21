"""Coleta única da arte dos efeitos, feita pelo navegador do dono.

Duas barreiras, e é a combinação das duas que dita este desenho estranho:

1. O Cloudflare da backpack.tf devolve **403 a cliente que não é navegador** —
   medido, com e sem cabeçalhos de navegador forjados. Então quem busca tem
   de ser um navegador.
2. Um `fetch` para a backpack.tf a partir de uma página servida daqui é
   **cross-origin, e o CORS recusa a leitura dos bytes**. A primeira versão
   desta ferramenta ignorava isso e falhava nos 547, silenciosamente, porque
   toda falha parecia "efeito sem arte na fonte".

Ou seja: a busca precisa rodar **de dentro de uma aba da própria
backpack.tf**, onde é same-origin. Este módulo é o outro lado — um servidor
local que recebe os bytes e grava em disco.

Uso:

    python -m tf2price.efeitos.coletor

Ele imprime o trecho a colar no console de uma aba aberta em
https://backpack.tf. O envio de volta usa `mode: "no-cors"` com corpo
`text/plain`, que é requisição simples e dispensa preflight.

Conferir depois de coletar, sempre:

    python -m tf2price.efeitos.coletor --verificar

Agrupa os arquivos por hash. Se muitos ids tiverem bytes idênticos, a fonte
devolveu imagem de ausência e aqueles precisam ser apagados — senão viram
aura confiante de um efeito que não tem arte.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from tf2price.domain.effects import DEFAULT_EFFECTS_PATH
from tf2price.efeitos.arte import DIRETORIO

PORTA = 8765
FONTE = "https://backpack.tf/images/440/particles/{id}_188x188.png"
# Same-origin: o fetch da própria página do coletor não manda `Origin`.
# Qualquer outra aba aberta no navegador manda, e é a que recusamos.
# Duas, porque as duas chegam aqui: quem digita `localhost` e quem digita
# `127.0.0.1` são a mesma pessoa, e recusar uma delas faria a coleta gravar
# zero arquivo enquanto a barra de progresso avança normalmente.
ORIGENS_PERMITIDAS = (
    f"http://127.0.0.1:{PORTA}",
    f"http://localhost:{PORTA}",
    # A busca precisa sair de dentro da própria backpack.tf: servida daqui,
    # ela é cross-origin e o navegador recusa ler os bytes por CORS. Então a
    # página de lá é que busca e manda para cá, e esta origem tem de passar.
    "https://backpack.tf",
)


def ids_a_coletar(effects_path: Path | None = None) -> list[int]:
    """Ids dos efeitos com nome de verdade.

    O schema traz entradas como `Attrib_Particle140`, que são reservas sem
    nome publicado e nunca aparecem no mercado.
    """
    mapa = json.loads((effects_path or DEFAULT_EFFECTS_PATH).read_text(encoding="utf-8"))
    return sorted(v for k, v in mapa.items() if not k.startswith("Attrib_Particle"))


def gravar(ident: int, dados: bytes, diretorio: Path | None = None) -> Path:
    if not isinstance(ident, int) or ident <= 0:
        raise ValueError(f"id inválido: {ident!r}")
    destino = diretorio or DIRETORIO
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{ident}.webp"
    caminho.write_bytes(dados)
    return caminho


def verificar(diretorio: Path | None = None) -> dict[str, list[int]]:
    """Agrupa a arte já coletada por hash do conteúdo.

    A única conferência do coletor hoje é `if (!r.ok)`: um 200 com um PNG
    genérico de "sem imagem" vira arte confiante de um efeito que não tem
    arte. Se dezenas de ids compartilham os mesmos bytes, é placeholder — e
    são bytes idênticos, não "parecidos", que este agrupamento por SHA-256
    detecta sem precisar abrir nenhum dos 547 arquivos manualmente.
    """
    destino = diretorio or DIRETORIO
    por_hash: dict[str, list[int]] = defaultdict(list)
    for arquivo in sorted(destino.glob("*.webp")):
        try:
            ident = int(arquivo.stem)
        except ValueError:
            continue
        digesto = hashlib.sha256(arquivo.read_bytes()).hexdigest()
        por_hash[digesto].append(ident)
    return {h: ids for h, ids in por_hash.items() if len(ids) > 1}


TRECHO = """(async () => {
  const ids = IDS_AQUI;
  const semArte = [], erros = [];
  let enviados = 0;
  for (const id of ids) {
    try {
      const r = await fetch(`/images/440/particles/${id}_188x188.png`);
      if (!r.ok) { semArte.push(id); }
      else {
        const bmp = await createImageBitmap(await r.blob());
        const c = document.createElement("canvas");
        c.width = bmp.width; c.height = bmp.height;
        c.getContext("2d").drawImage(bmp, 0, 0);
        const webp = await new Promise(res => c.toBlob(res, "image/webp", 0.85));
        // text/plain deixa a requisicao "simples": sem preflight, que o
        // servidor local nao sabe responder.
        await fetch(`http://127.0.0.1:PORTA_AQUI/gravar/${id}`, {
          method: "POST", mode: "no-cors",
          body: new Blob([webp], { type: "text/plain" }),
        });
        enviados++;
      }
    } catch (e) { erros.push(id); }
    if (ids.indexOf(id) % 25 === 0) console.log(`${ids.indexOf(id)}/${ids.length}`);
    await new Promise(res => setTimeout(res, 250));
  }
  console.log({ enviados, semArte: semArte.length, erros: erros.length, semArteIds: semArte });
})();"""


PAGINA = """<!doctype html>
<meta charset="utf-8">
<title>Coletor de arte</title>
<style>
  body { font-family: system-ui; max-width: 46rem; margin: 3rem auto; padding: 0 1rem;
         line-height: 1.5; }
  pre { background: #f4f4f5; padding: 1rem; overflow-x: auto; font-size: .78rem; }
  .aviso { border-left: 4px solid #d08b00; background: #fff4e5; padding: .8rem 1rem; }
</style>
<h1>Coletor de arte dos efeitos</h1>

<p class="aviso"><b>Esta página não busca nada sozinha, e não é descuido.</b>
Um <code>fetch</code> daqui para a backpack.tf é cross-origin, e o navegador
recusa ler os bytes. A busca precisa rodar de dentro de uma aba da própria
backpack.tf.</p>

<ol>
  <li>Abra <a href="https://backpack.tf" target="_blank">https://backpack.tf</a>
      numa aba.</li>
  <li>Abra o console do navegador nessa aba (F12).</li>
  <li>Cole o trecho abaixo e dê Enter. Leva uns três minutos; o console vai
      contando.</li>
  <li>Volte aqui e feche este servidor. Depois rode
      <code>python -m tf2price.efeitos.coletor --verificar</code>.</li>
</ol>

<pre id="trecho">TRECHO_AQUI</pre>
"""


class _Tratador(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        trecho = (
            TRECHO.replace("IDS_AQUI", json.dumps(ids_a_coletar()))
            .replace("PORTA_AQUI", str(PORTA))
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        corpo = PAGINA.replace("TRECHO_AQUI", trecho).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_POST(self) -> None:  # noqa: N802
        # Enquanto o servidor local roda, qualquer aba aberta no navegador
        # pode mandar um POST para cá. O nome do arquivo já está preso a
        # `\d+.webp` (sem escrita fora do diretório), mas isto ainda seria
        # escrita não solicitada; recusamos quem não é a própria página.
        origem = self.headers.get("Origin")
        if origem is not None and origem not in ORIGENS_PERMITIDAS:
            self.send_response(403)
            self.end_headers()
            return

        tamanho = int(self.headers.get("Content-Length", 0))
        dados = self.rfile.read(tamanho)
        if self.path.startswith("/gravar/"):
            try:
                ident = int(self.path.rsplit("/", 1)[1])
            except ValueError:
                self.send_response(400)
                self.end_headers()
                return
            gravar(ident, dados)
        elif self.path == "/fim":
            faltaram = json.loads(dados or b"[]")
            print(f"\nColeta terminada. Sem arte na fonte: {len(faltaram)}")
            if faltaram:
                print("ids:", ", ".join(str(i) for i in faltaram))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args) -> None:
        pass  # o progresso aparece na página, não no terminal


def relatorio_de_verificacao(grupos: dict[str, list[int]]) -> str:
    if not grupos:
        return "nenhum grupo com bytes repetidos."
    linhas = [f"{len(grupos)} grupo(s) com bytes idênticos (provável placeholder):"]
    for ids in grupos.values():
        linhas.append(f"  {len(ids)} arquivos iguais: {', '.join(str(i) for i in ids)}")
    return "\n".join(linhas)


def main() -> None:
    if "--verificar" in sys.argv[1:]:
        print(relatorio_de_verificacao(verificar()))
        return
    print(f"Abra http://127.0.0.1:{PORTA} — ele traz o trecho para colar")
    print("no console de uma aba da backpack.tf (a busca precisa sair de lá).")
    print(f"As imagens vão para {DIRETORIO}")
    HTTPServer(("127.0.0.1", PORTA), _Tratador).serve_forever()


if __name__ == "__main__":
    main()
