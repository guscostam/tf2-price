"""Coleta única da arte dos efeitos, feita pelo navegador do dono.

O Cloudflare da backpack.tf devolve 403 a cliente que não é navegador —
medido, com e sem cabeçalhos de navegador falsos. Então quem busca é o
navegador, numa página servida daqui, e quem grava é este servidor local.

Roda uma vez:

    python -m tf2price.efeitos.coletor

Abre http://127.0.0.1:8765, clica em começar, espera, e o relatório final diz
quantas vieram e quais faltaram.
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
ORIGENS_PERMITIDAS = (f"http://127.0.0.1:{PORTA}", f"http://localhost:{PORTA}")


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


PAGINA = """<!doctype html>
<meta charset="utf-8">
<title>Coletor de arte</title>
<style>
  body { font-family: system-ui; max-width: 40rem; margin: 3rem auto; padding: 0 1rem; }
  progress { width: 100%; height: 1.2rem; }
  #faltaram { font-family: ui-monospace, monospace; font-size: .85rem; color: #b3261e; }
</style>
<h1>Coletor de arte dos efeitos</h1>
<p>Busca cada efeito na backpack.tf, converte para WebP e envia para este
servidor local, que grava em <code>tf2price/data/efeitos/</code>. Uma pausa de
300 ms entre as buscas, para não bater na fonte sem educação.</p>
<button id="ir">Começar</button>
<p><progress id="barra" value="0" max="1"></progress> <span id="conta"></span></p>
<p id="faltaram"></p>
<script>
const ids = IDS_AQUI;
document.getElementById("ir").onclick = async () => {
  const barra = document.getElementById("barra");
  const conta = document.getElementById("conta");
  barra.max = ids.length;
  let vieram = 0;
  const faltaram = [];
  const recusados = [];
  for (let i = 0; i < ids.length; i++) {
    const id = ids[i];
    try {
      const r = await fetch(`https://backpack.tf/images/440/particles/${id}_188x188.png`);
      if (!r.ok) { faltaram.push(id); }
      else {
        const bmp = await createImageBitmap(await r.blob());
        const c = document.createElement("canvas");
        c.width = bmp.width; c.height = bmp.height;
        c.getContext("2d").drawImage(bmp, 0, 0);
        const webp = await new Promise(res => c.toBlob(res, "image/webp", 0.85));
        // Conferir a resposta: sem isto, um POST recusado contaria como
        // gravado e o relatório mentiria com a barra cheia.
        const g = await fetch(`/gravar/${id}`, { method: "POST", body: webp });
        if (!g.ok) { recusados.push(id); } else { vieram++; }
      }
    } catch (e) { faltaram.push(id); }
    barra.value = i + 1;
    conta.textContent = `${i + 1} de ${ids.length} — ${vieram} gravadas`;
    await new Promise(r => setTimeout(r, 300));
  }
  const partes = [];
  if (faltaram.length) partes.push(`sem arte na fonte (${faltaram.length}): ${faltaram.join(", ")}`);
  if (recusados.length) partes.push(`RECUSADAS PELO SERVIDOR (${recusados.length}) — algo está errado: ${recusados.join(", ")}`);
  document.getElementById("faltaram").textContent = partes.length ? partes.join(" | ") : "todas vieram";
  await fetch("/fim", { method: "POST", body: JSON.stringify(faltaram) });
};
</script>
"""


class _Tratador(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        corpo = PAGINA.replace("IDS_AQUI", json.dumps(ids_a_coletar())).encode("utf-8")
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
    print(f"Abra http://127.0.0.1:{PORTA} e clique em Começar.")
    print(f"As imagens vão para {DIRETORIO}")
    HTTPServer(("127.0.0.1", PORTA), _Tratador).serve_forever()


if __name__ == "__main__":
    main()
