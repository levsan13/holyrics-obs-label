#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Holyrics -> OBS

Sobe um servidor local que serve UMA página contendo só a letra que está no ar
no Holyrics, já com o CSS personalizado e fundo transparente, pronta para virar
uma fonte de navegador no OBS.

    python3 script.py

Toda a configuração fica no arquivo .env ao lado deste script.
Só usa a biblioteca padrão do Python 3.8+. Ctrl+C encerra.
"""

import argparse
import base64
import json
import math
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

AQUI = os.path.dirname(os.path.abspath(__file__))

# Valores usados quando a chave não está no .env nem no ambiente.
PADROES = {
    "HOLYRICS_URL": "http://192.168.0.6",
    "HOST": "127.0.0.1",
    "PORTA": "8080",

    "LARGURA": "1628",
    "ALTURA": "236",
    "MARGEM_H": "56",
    "MARGEM_V": "10",

    "FAMILIA": "Montserrat, Segoe UI, Arial, Helvetica, sans-serif",
    "PESO": "800",
    "ENTRELINHA": "1.14",
    "ESPACAMENTO": "0.004",
    "CAIXA_ALTA": "false",
    "TAMANHO_MAX": "72",
    "TAMANHO_MIN": "14",

    "COR": "#FFFFFF",
    "COR_CONTORNO": "#000000",
    "CONTORNO": "0.056",
    "SOMBRA": "0.60",
    "FUNDO": "",

    "INTERVALO": "100",
    "FADE": "160",
    "MOSTRAR_REFERENCIA": "false",
    "LIMPAR_APOS_ERROS": "30",
    "BAIXAR_FONTE": "true",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
FONTE_CSS_URL = "https://fonts.googleapis.com/css2?family=Montserrat:wght@800&display=swap"
GENERICAS = {"sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui", "ui-sans-serif"}

FAVICON = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=")

CFG = None          # preenchido em main()
FONTE_BYTES = None  # woff2 da Montserrat, se disponível
_ultimo_erro = None


# =============================================================================
#  .env
# =============================================================================

def ler_env(caminho):
    """Leitor de .env sem dependências: KEY=valor, # comentário, aspas opcionais."""
    dados = {}
    if not caminho or not os.path.exists(caminho):
        return dados
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            if linha.lower().startswith("export "):
                linha = linha[7:].lstrip()
            if "=" not in linha:
                continue
            chave, _, valor = linha.partition("=")
            chave, valor = chave.strip(), valor.strip()
            # comentário no fim da linha só conta se vier depois de espaço,
            # para não cortar valores como COR=#FFFFFF
            if valor[:1] not in ('"', "'"):
                corte = re.search(r"\s+#", valor)
                if corte:
                    valor = valor[:corte.start()].rstrip()
            if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ('"', "'"):
                valor = valor[1:-1]
            dados[chave] = valor
    return dados


def montar_config(caminho_env):
    """Precedência: variável de ambiente do sistema > .env > PADROES."""
    arquivo = ler_env(caminho_env)

    def bruto(k):
        return os.environ.get(k, arquivo.get(k, PADROES[k]))

    def inteiro(k):
        try:
            return int(float(bruto(k)))
        except ValueError:
            print(f"  [!] {k} inválido no .env; usando {PADROES[k]}")
            return int(float(PADROES[k]))

    def decimal(k):
        try:
            return float(bruto(k))
        except ValueError:
            print(f"  [!] {k} inválido no .env; usando {PADROES[k]}")
            return float(PADROES[k])

    def logico(k):
        return bruto(k).strip().lower() in ("1", "true", "sim", "yes", "on")

    c = SimpleNamespace(
        holyrics=bruto("HOLYRICS_URL").rstrip("/"),
        host=bruto("HOST"),
        porta=inteiro("PORTA"),
        largura=inteiro("LARGURA"),
        altura=inteiro("ALTURA"),
        margem_h=inteiro("MARGEM_H"),
        margem_v=inteiro("MARGEM_V"),
        familia=css_familia(bruto("FAMILIA")),
        peso=inteiro("PESO"),
        entrelinha=decimal("ENTRELINHA"),
        espacamento=decimal("ESPACAMENTO"),
        caixa_alta=logico("CAIXA_ALTA"),
        tamanho_max=inteiro("TAMANHO_MAX"),
        tamanho_min=inteiro("TAMANHO_MIN"),
        cor=bruto("COR"),
        cor_contorno=bruto("COR_CONTORNO"),
        contorno=decimal("CONTORNO"),
        sombra=decimal("SOMBRA"),
        fundo=bruto("FUNDO").strip(),
        intervalo=inteiro("INTERVALO"),
        fade=inteiro("FADE"),
        referencia=logico("MOSTRAR_REFERENCIA"),
        limpar_apos=inteiro("LIMPAR_APOS_ERROS"),
        baixar_fonte=logico("BAIXAR_FONTE"),
        env=caminho_env if os.path.exists(caminho_env or "") else None,
    )
    if c.tamanho_min > c.tamanho_max:
        c.tamanho_min, c.tamanho_max = c.tamanho_max, c.tamanho_min
    return c


def css_familia(valor):
    """'Montserrat, Segoe UI, Arial' -> "'Montserrat', 'Segoe UI', Arial" """
    saida = []
    for nome in valor.split(","):
        nome = nome.strip().strip("'\"")
        if not nome:
            continue
        if " " in nome and nome.lower() not in GENERICAS:
            nome = f"'{nome}'"
        saida.append(nome)
    return ", ".join(saida) or "sans-serif"


# =============================================================================
#  Fonte — baixa a Montserrat uma vez e passa a servir do disco.
#  Sem internet, a página cai no próximo nome da lista FAMILIA.
# =============================================================================

def caminho_cache():
    for base in (AQUI, tempfile.gettempdir()):
        try:
            p = os.path.join(base, "montserrat-800.woff2")
            open(p, "ab").close()
            return p
        except OSError:
            continue
    return None


def carregar_fonte(cfg):
    global FONTE_BYTES
    if not cfg.baixar_fonte:
        print("  fonte .........: download desligado no .env (BAIXAR_FONTE)")
        return
    cache = caminho_cache()
    if cache and os.path.exists(cache) and os.path.getsize(cache) > 1000:
        try:
            with open(cache, "rb") as f:
                FONTE_BYTES = f.read()
            print("  fonte .........: Montserrat (cache local)")
            return
        except OSError:
            pass
    try:
        req = urllib.request.Request(FONTE_CSS_URL, headers={"User-Agent": UA})
        css = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "replace")
        # o bloco comentado como /* latin */ cobre o português inteiro
        m = (re.search(r"/\*\s*latin\s*\*/[^}]*?src:\s*url\((https://[^)]+?\.woff2)\)", css)
             or re.search(r"url\((https://[^)]+?\.woff2)\)", css))
        if not m:
            raise ValueError("woff2 nao encontrado no CSS do Google Fonts")
        FONTE_BYTES = urllib.request.urlopen(
            urllib.request.Request(m.group(1), headers={"User-Agent": UA}), timeout=10).read()
        if cache:
            try:
                with open(cache, "wb") as f:
                    f.write(FONTE_BYTES)
            except OSError:
                pass
        print("  fonte .........: Montserrat baixada e guardada para uso offline")
    except Exception as e:
        print(f"  fonte .........: sem internet para a Montserrat ({e.__class__.__name__}); "
              f"a página usa a próxima fonte da lista")


# =============================================================================
#  CSS
# =============================================================================

def anel_contorno(cfg):
    """Contorno fechado em 12 direções + sombra suave, em 'em' para acompanhar
    o tamanho da letra."""
    r = cfg.contorno
    partes = [f"{r * math.cos(math.radians(i * 30)):.4f}em "
              f"{r * math.sin(math.radians(i * 30)):.4f}em 0 {cfg.cor_contorno}"
              for i in range(12)]
    partes.append(f"0 {r * 1.6:.4f}em {r * 2.8:.4f}em rgba(0,0,0,{cfg.sombra})")
    return ",\n    ".join(partes)


def montar_css(cfg):
    face = ""
    if FONTE_BYTES:
        face = ("@font-face{font-family:'Montserrat';font-style:normal;font-weight:800;"
                "font-display:block;src:url('/fonte.woff2') format('woff2');}\n")
    return f"""{face}html,body{{
  margin:0; padding:0; width:100%; height:100%;
  overflow:hidden; background:transparent;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}}

#palco{{
  position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
  width:{cfg.largura}px; height:{cfg.altura}px;
  max-width:100vw; max-height:100vh;
  overflow:hidden;
  background:{cfg.fundo or "transparent"};
}}

#letra, #medidor{{
  position:absolute;
  left:{cfg.margem_h}px; right:{cfg.margem_h}px;
  font-family:{cfg.familia};
  font-weight:{cfg.peso};
  color:{cfg.cor};
  line-height:{cfg.entrelinha};
  letter-spacing:{cfg.espacamento}em;
  text-transform:{"uppercase" if cfg.caixa_alta else "none"};
  text-align:center;
  word-wrap:break-word;
  overflow-wrap:break-word;
  text-wrap:balance;
  text-shadow:
    {anel_contorno(cfg)};
}}

#letra{{ top:50%; transform:translateY(-50%); transition:opacity {cfg.fade}ms linear; }}
#medidor{{ top:0; visibility:hidden; pointer-events:none; }}
.ref{{ font-size:62%; opacity:.92; }}
"""


# =============================================================================
#  Página
# =============================================================================

JS = r"""
const CFG = @@CFG@@;

const palco = document.getElementById('palco');
const letra = document.getElementById('letra');
const med   = document.getElementById('medidor');

let imgId = '', atual = null, erros = 0, seq = 0;

/* tira do HTML que vem do Holyrics tudo que possa executar algo */
function limpar(h){
  if (h === null || h === undefined) return '';
  return String(h)
    .replace(/<\s*\/?\s*(script|iframe|object|embed|link|meta|style)\b[^>]*>/gi, '')
    .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
    .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
    .replace(/\son\w+\s*=\s*[^\s>]+/gi, '');
}

/* maior tamanho de fonte em que a estrofe ainda cabe na barra (busca binária) */
function calcular(html){
  med.innerHTML = html;
  const alturaUtil  = palco.clientHeight - CFG.margemV * 2;
  const larguraUtil = med.clientWidth + 1;
  let lo = CFG.min, hi = CFG.max, melhor = CFG.min;
  while (lo <= hi){
    const meio = (lo + hi) >> 1;
    med.style.fontSize = meio + 'px';
    if (med.scrollHeight <= alturaUtil && med.scrollWidth <= larguraUtil){
      melhor = meio; lo = meio + 1;
    } else {
      hi = meio - 1;
    }
  }
  return melhor;
}

function aplicar(html){
  const px = calcular(html);
  const meu = ++seq;                       /* se a estrofe virar de novo antes do
                                              fade acabar, só a última vale */
  if (CFG.fade > 0){
    letra.style.opacity = '0';
    setTimeout(() => {
      if (meu !== seq) return;
      letra.style.fontSize = px + 'px';
      letra.innerHTML = html;
      letra.style.opacity = '1';
    }, CFG.fade);
  } else {
    letra.style.fontSize = px + 'px';
    letra.innerHTML = html;
    letra.style.opacity = '1';
  }
}

async function consultar(){
  try {
    const q = '/text.json?html_type=0&img_id=' + encodeURIComponent(imgId) +
              '&css_hash=0&css_extra_name=&css_extra_hash=0';
    const r = await fetch(q, {cache: 'no-store'});
    if (!r.ok) throw new Error('http ' + r.status);
    const m = (await r.json()).map || {};
    erros = 0;

    if (typeof m.img_id === 'string' && m.img_id !== 'equals') imgId = m.img_id;

    let t = limpar(m.text);
    if (CFG.ref && m.header){
      t = "<span class='ref'>" + limpar(m.header).replace(/\n/g, '<br>') + "</span><br>" + t;
    }
    if (t !== atual){ atual = t; aplicar(t); }

  } catch (e) {
    /* Holyrics fora do ar: segura a última estrofe por alguns instantes e só
       então limpa, para não piscar em falha de rede passageira */
    if (++erros >= CFG.limpar && atual !== ''){ atual = ''; aplicar(''); }
  } finally {
    setTimeout(consultar, CFG.intervalo);
  }
}

let redim;
addEventListener('resize', () => {
  clearTimeout(redim);
  redim = setTimeout(() => {
    if (atual !== null) letra.style.fontSize = calcular(atual) + 'px';
  }, 120);
});

/* espera a fonte carregar antes da primeira medição, senão o cálculo sai errado */
(document.fonts ? document.fonts.ready : Promise.resolve()).then(consultar);
"""


def montar_pagina(cfg):
    cfg_js = json.dumps({
        "intervalo": cfg.intervalo,
        "fade": cfg.fade,
        "min": cfg.tamanho_min,
        "max": cfg.tamanho_max,
        "margemV": cfg.margem_v,
        "ref": cfg.referencia,
        "limpar": cfg.limpar_apos,
    })
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Holyrics</title>
<style>
{montar_css(cfg)}</style>
</head>
<body>
<div id="palco"><div id="letra"></div><div id="medidor" aria-hidden="true"></div></div>
<script>
{JS.replace("@@CFG@@", cfg_js)}
</script>
</body>
</html>
"""


# =============================================================================
#  Servidor
# =============================================================================

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HolyricsOBS/1.1"

    def log_message(self, *a):
        pass  # terminal limpo; só erros de conexão aparecem

    def _responder(self, corpo, tipo, status=200, cache=False):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control",
                         "public, max-age=31536000, immutable" if cache else "no-store")
        self.end_headers()
        try:
            self.wfile.write(corpo)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        rota = urllib.parse.urlparse(self.path)

        if rota.path in ("/", "/index.html"):
            self._responder(montar_pagina(CFG), "text/html; charset=utf-8")

        elif rota.path == "/text.json":
            self._proxy(rota.query)

        elif rota.path == "/favicon.ico":
            self._responder(FAVICON, "image/png", cache=True)

        elif rota.path == "/fonte.woff2":
            if FONTE_BYTES:
                self._responder(FONTE_BYTES, "font/woff2", cache=True)
            else:
                self._responder(b"", "font/woff2", status=404)

        else:
            self._responder(b"", "text/plain", status=404)

    def _proxy(self, query):
        """Repassa a consulta para o Holyrics. Como a página e o JSON saem do
        mesmo host, o navegador não vê requisição cross-origin."""
        global _ultimo_erro
        url = f"{CFG.holyrics}/view/text.json" + (f"?{query}" if query else "")
        try:
            req = urllib.request.Request(
                url, headers={"Accept": "application/json", "User-Agent": "HolyricsOBS"})
            with urllib.request.urlopen(req, timeout=3) as r:
                self._responder(r.read(), "application/json; charset=utf-8")
            if _ultimo_erro:
                _ultimo_erro = None
                print("  [ok] Holyrics respondendo de novo")
        except Exception as e:
            if _ultimo_erro != e.__class__.__name__:
                _ultimo_erro = e.__class__.__name__
                print(f"  [!] sem resposta do Holyrics em {CFG.holyrics} ({e.__class__.__name__})")
            self._responder(json.dumps({"erro": e.__class__.__name__}),
                            "application/json; charset=utf-8", status=502)


# =============================================================================
#  Início
# =============================================================================

def main():
    global CFG

    ap = argparse.ArgumentParser(
        description="Serve a letra do Holyrics como página local para o OBS. "
                    "A configuração fica no .env; os argumentos abaixo têm prioridade.")
    ap.add_argument("--env", default=os.path.join(AQUI, ".env"), metavar="ARQ",
                    help="caminho do .env (padrão: .env ao lado do script)")
    ap.add_argument("--holyrics", metavar="URL")
    ap.add_argument("--porta", type=int, metavar="N")
    ap.add_argument("--host", metavar="IP",
                    help="0.0.0.0 se o OBS estiver em OUTRO computador da rede")
    ap.add_argument("--largura", type=int, metavar="PX")
    ap.add_argument("--altura", type=int, metavar="PX")
    a = ap.parse_args()

    CFG = montar_config(a.env)
    for campo in ("holyrics", "porta", "host", "largura", "altura"):
        valor = getattr(a, campo)
        if valor is not None:
            setattr(CFG, campo, valor.rstrip("/") if campo == "holyrics" else valor)

    print("\n  Holyrics -> OBS")
    print(f"  config ........: {CFG.env or 'sem .env — usando os valores padrão'}")
    print(f"  letra .........: {CFG.holyrics}/view/text.json")
    carregar_fonte(CFG)
    print(f"  tamanho .......: {CFG.largura} x {CFG.altura}")

    endereco = "localhost" if CFG.host in ("127.0.0.1", "0.0.0.0") else CFG.host
    print(f"\n  No OBS, fonte Navegador com a URL:  http://{endereco}:{CFG.porta}")
    print(f"  Largura {CFG.largura}   Altura {CFG.altura}   (campo CSS do OBS pode ficar vazio)")
    print("\n  Ctrl+C para encerrar.\n")

    try:
        servidor = ThreadingHTTPServer((CFG.host, CFG.porta), Handler)
    except OSError as e:
        print(f"  [x] não consegui abrir {CFG.host}:{CFG.porta} ({e.strerror}).")
        print("      A porta já está em uso? Troque PORTA no .env ou use --porta.\n")
        sys.exit(1)

    servidor.daemon_threads = True
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n  encerrado.\n")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
