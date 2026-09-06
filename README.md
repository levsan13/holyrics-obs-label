# Holyrics → OBS

Servidor local que publica **apenas a letra** que está no ar no Holyrics, já
estilizada e com fundo transparente, pronta para virar uma fonte de navegador
no OBS.

Sem botões, sem miniaturas, sem título de música: a página tem só o texto.

![Exemplo da barra em 1628 × 236 sobre três fundos diferentes](docs/preview.png)

---

## Por que existe

A própria página do Holyrics (`/view/text`) já pode ser usada direto no OBS,
mas ela dimensiona a letra assim:

```
tamanho = altura_da_área ÷ max(nº de linhas, 100 ÷ font_max_rows)
```

Com o padrão `font_max_rows = 10`, uma barra de 236 px de altura recebe letra
de **~20 px** — ilegível em transmissão. Além disso vêm juntos o alerta, o
contador de página e os campos de título.

Este projeto resolve os dois lados: lê o JSON que o Holyrics já expõe e monta
a própria página, calculando por **busca binária** o maior tamanho de fonte em
que a estrofe ainda cabe na barra.

---

## Como funciona

```
navegador do OBS  ──GET /            ──►  script.py  ──►  página + CSS
                  ──GET /text.json   ──►  script.py  ──►  http://SEU_IP/view/text.json
```

- A página consulta `/text.json` a cada 100 ms — o mesmo intervalo que o
  Holyrics usa internamente.
- O script repassa a consulta ao Holyrics. Como página e JSON saem do mesmo
  host, o navegador não vê requisição *cross-origin* e não há CORS.
- Do JSON só é aproveitado o campo `map.text` (a letra, com `<br>` entre as
  linhas). Alerta, imagem de fundo, contador de página e nomes de música são
  descartados. O HTML recebido é higienizado antes de entrar na página.
- A cada troca de estrofe o tamanho é recalculado e aplicado com um *fade*
  curto.
- Se o Holyrics cair, a última estrofe fica no ar por ~3 s antes de apagar, e
  volta sozinha quando o Holyrics responder de novo — sem piscar em falha de
  rede passageira.
- A fonte Montserrat é baixada uma única vez e guardada em disco, então da
  segunda execução em diante tudo funciona **sem internet**.

---

## Requisitos

- Python 3.8 ou mais novo — **nenhuma dependência externa**, só a biblioteca padrão
- Holyrics com o servidor web ligado
  (Configurações → Avançado → **Servidor web**)
- OBS Studio

---

## Uso

```bash
git clone <url-do-seu-repositorio> holyrics-obs
cd holyrics-obs

cp .env.example .env      # ajuste o IP do Holyrics e o resto
python3 script.py
```

Saída esperada:

```
  Holyrics -> OBS
  config ........: /caminho/holyrics-obs/.env
  letra .........: http://192.168.0.6/view/text.json
  fonte .........: Montserrat baixada e guardada para uso offline
  tamanho .......: 1628 x 236

  No OBS, fonte Navegador com a URL:  http://localhost:8080
  Largura 1628   Altura 236   (campo CSS do OBS pode ficar vazio)
```

### No OBS

1. **+** → **Navegador**
2. **URL:** `http://localhost:8080`
3. **Largura** `1628`  ·  **Altura** `236` — os mesmos valores de `LARGURA` e
   `ALTURA` no `.env`
4. **CSS personalizado:** deixe vazio (o estilo já vem na página)
5. Marque *Desligar a fonte quando não estiver visível* se quiser poupar CPU

O script precisa estar rodando enquanto o OBS estiver no ar.

### Argumentos de linha de comando

Úteis para testar sem mexer no `.env` — têm prioridade sobre ele:

```bash
python3 script.py --porta 9000
python3 script.py --holyrics http://192.168.0.20
python3 script.py --host 0.0.0.0          # OBS em outro computador da rede
python3 script.py --env ../outro/.env
```

---

## Configuração

Tudo fica no `.env`. Cada linha é opcional: o que faltar cai no padrão.

A ordem de prioridade é **argumento de linha de comando → variável de ambiente
do sistema → `.env` → padrão**.

### Conexão

| Variável | Padrão | O que faz |
|---|---|---|
| `HOLYRICS_URL` | `http://192.168.0.6` | Endereço do servidor web do Holyrics, sem `/view` no fim |
| `HOST` | `127.0.0.1` | Onde a página fica disponível. `0.0.0.0` libera para a rede local |
| `PORTA` | `8080` | Porta da página local |

### Tamanho da barra

| Variável | Padrão | O que faz |
|---|---|---|
| `LARGURA` | `1628` | Precisa bater com a Largura da fonte no OBS |
| `ALTURA` | `236` | Precisa bater com a Altura da fonte no OBS |
| `MARGEM_H` | `56` | Respiro nas laterais, em px |
| `MARGEM_V` | `10` | Respiro em cima e embaixo, em px |

### Tipografia

| Variável | Padrão | O que faz |
|---|---|---|
| `FAMILIA` | `Montserrat, Segoe UI, Arial, Helvetica, sans-serif` | Fontes em ordem de preferência, separadas por vírgula |
| `PESO` | `800` | 700 bold · 800 extrabold · 900 black |
| `ENTRELINHA` | `1.14` | Espaço entre as linhas |
| `ESPACAMENTO` | `0.004` | `letter-spacing` em `em`; negativo aperta |
| `CAIXA_ALTA` | `false` | `true` deixa tudo em MAIÚSCULAS |
| `TAMANHO_MAX` | `72` | Teto do ajuste automático, em px — veja a nota abaixo |
| `TAMANHO_MIN` | `14` | Piso, para estrofes muito longas não sumirem |

> **Sobre `TAMANHO_MAX`:** é o tamanho que uma estrofe curta vai ter. Quanto
> mais baixo, mais constante fica a letra entre um slide e outro; quanto mais
> alto, mais os versos curtos crescem. Se a letra estiver "pulando" de tamanho
> a cada virada, baixe esse valor até que os slides comuns fiquem todos iguais.

### Cores

| Variável | Padrão | O que faz |
|---|---|---|
| `COR` | `#FFFFFF` | Cor da letra |
| `COR_CONTORNO` | `#000000` | Cor do contorno |
| `CONTORNO` | `0.056` | Espessura do contorno em `em` — acompanha o tamanho da letra |
| `SOMBRA` | `0.60` | Opacidade (0 a 1) da sombra suave por baixo do contorno |
| `FUNDO` | *(vazio)* | Fundo da barra. Vazio = transparente |

### Comportamento

| Variável | Padrão | O que faz |
|---|---|---|
| `INTERVALO` | `100` | Milissegundos entre consultas ao Holyrics |
| `FADE` | `160` | Transição ao trocar de estrofe, em ms. `0` desliga |
| `MOSTRAR_REFERENCIA` | `false` | `true` mostra a referência bíblica acima do versículo |
| `LIMPAR_APOS_ERROS` | `30` | Consultas falhas seguidas antes de apagar a letra |
| `BAIXAR_FONTE` | `true` | Baixa a Montserrat na 1ª execução e guarda para uso offline |

---

## Ajustes comuns

**Faixa escura atrás da letra** — garante leitura sobre qualquer imagem:

```env
FUNDO=rgba(0,0,0,0.65)
```

**Letra em caixa alta e mais apertada:**

```env
CAIXA_ALTA=true
ESPACAMENTO=-0.01
```

**Contorno mais grosso** (fundos muito claros ou muito movimentados):

```env
CONTORNO=0.075
SOMBRA=0.75
```

**Sem transição** — a estrofe troca instantaneamente:

```env
FADE=0
```

**OBS em outro computador da rede** — libere o host e use o IP da máquina que
roda o script na URL da fonte de navegador (`http://192.168.0.x:8080`):

```env
HOST=0.0.0.0
```

**Outra fonte, já instalada na máquina** — desligue o download e coloque o nome
dela na frente da lista:

```env
BAIXAR_FONTE=false
FAMILIA=Bebas Neue, Impact, Arial, sans-serif
```

---

## Estrutura

```
holyrics-obs/
├── script.py        servidor, CSS e página (biblioteca padrão apenas)
├── .env.example     modelo de configuração, comentado
├── .env             sua configuração — fora do versionamento
├── .gitignore
├── LICENSE
├── README.md
└── docs/
    └── preview.png
```

O `.env` e o `montserrat-800.woff2` ficam de fora do Git: são de cada máquina.

---

## Solução de problemas

**A página abre em branco e não aparece letra nenhuma**
Confira se há algo projetado no Holyrics. Sem slide no ar, `map.text` vem
vazio e a barra fica transparente de propósito.

**`[!] sem resposta do Holyrics em http://...`**
O IP em `HOLYRICS_URL` está errado, o servidor web do Holyrics está desligado
ou o firewall está bloqueando. Teste abrindo `http://SEU_IP/view/text` no
navegador da mesma máquina que roda o script.

**`[x] não consegui abrir 127.0.0.1:8080`**
A porta já está ocupada. Troque `PORTA` no `.env` (ou use `--porta`) e ajuste
a URL da fonte no OBS.

**A letra não está em Montserrat**
Na primeira execução é preciso internet para baixá-la. O terminal diz o que
aconteceu na linha `fonte .........:`. Depois de baixada uma vez, o arquivo
`montserrat-800.woff2` fica ao lado do script e não precisa mais de rede.

**A letra ficou pequena demais**
A estrofe é longa e o ajuste automático encolheu para caber. Reduza
`MARGEM_H` e `MARGEM_V`, aumente `ALTURA` ou configure o Holyrics para quebrar
o slide em menos linhas.

**A letra some por um instante ao trocar de slide**
Reduza `FADE` ou coloque `0`.

---

## Licença

MIT — veja [LICENSE](LICENSE).
