# Landing page do `briefcase.tf` — design

**Data:** 2026-09-21

**Status:** aprovado para planejamento

**Base funcional:** aplicação existente em `master`, após `0844076`

**Referência visual:** `C:\Users\gusco\Desktop\briefcase-tf-branding-completo\briefcase-tf-branding-package`
(logo, tokens, tela de login `03-login.png` e direção `approved-dossier-desk.png`)

---

## 1. Objetivo

Dar ao briefcase.tf uma porta de entrada pública que explique o produto e
**colete pedidos de convite**. O app continua fechado: não há cadastro aberto, e
toda conta nova continua nascendo de um convite gerado pelo administrador.

## 2. Decisões centrais

| Tema | Decisão |
| --- | --- |
| Objetivo da página | Pedir acesso; o app segue só por convite |
| Destino do pedido | Tabela no banco, listada em `/admin` |
| Dados do pedido | Perfil da Steam (obrigatório) + contato livre (obrigatório) + observação (opcional) |
| Demonstração do produto | Case File de exemplo em HTML/CSS, com valores fictícios rotulados |
| Onde mora | `GET /` sem sessão; com sessão, `/` continua sendo o Overview |
| Composição | Hero dividido: promessa e CTA à esquerda, dossiê de exemplo inclinado à direita |
| Idioma | Inglês, como o resto da interface |

Fora de escopo: cadastro aberto, preços/planos, depoimentos, FAQ, newsletter,
envio de e-mail, CAPTCHA ou qualquer serviço de terceiros.

## 3. Conteúdo, de cima para baixo

1. **Topo** — logo à esquerda; link discreto `Sign in` (`/entrar`) à direita.
   Sem menu.
2. **Hero** — linha mono *UNUSUAL MARKET INTELLIGENCE*; título (único `h1`)
   **Every Unusual Is a Case.**; subtítulo *"Evidence for this effect. Context
   for the item. A verdict before you buy."*; CTA principal `Request access`
   (âncora para `#access`) e secundário `See a sample case` (âncora para o
   exemplo). À direita, o Case File de exemplo (seção 6).
3. **How it works** — três fichas numeradas: *Pick the hat and effect* →
   *We collect the evidence* (listagens da Steam, preço da backpack.tf, livro de
   ofertas e histórico) → *Read the verdict* (Good Buy / Fair Price / Caution /
   Insufficient Data).
4. **THIS EFFECT ≠ ALL EFFECTS** — a regra central: dois chapéus com o mesmo
   nome e efeitos diferentes valem coisas diferentes; o briefcase nunca usa o
   preço de outro efeito e diz `Insufficient Data` em vez de inventar um valor.
   Duas colunas lado a lado, com a mesma distinção visual do app.
5. **What we've found** — número de destaque **1.72×**: na mediana, o preço da
   Steam fica 1,72× acima do valor de troca (fonte:
   `docs/superpowers/findings/2026-09-19-consulta-primeiro-uso.md`). Mensagem:
   a ferramenta existe para evitar um mau negócio pontual, não para prometer
   lucro ou arbitragem.
6. **Access file** (`id="access"`) — formulário de pedido (seção 5).
7. **Rodapé** — *Independent fan-made project. Not affiliated with Valve,
   Steam, or backpack.tf.*, tagline e `Sign in`.

## 4. Rotas

- **`GET /`** usa `usuario_opcional`.
  - Sem sessão: renderiza `landing.html`.
  - Com sessão: renderiza o Overview exatamente como hoje, na mesma URL.
  - A rota sai de `paginas.py` e vai para um módulo novo,
    `tf2price/painel/publico.py`, **sempre** montado em `criar_app` (inclusive
    com `contexto=None`). Para usuário logado, ela delega à mesma função que
    hoje monta o Overview; `paginas.py` mantém as demais rotas autenticadas.
  - Com `contexto=None` (montagem usada só em testes de autenticação) não há
    Overview possível: `/` responde a landing com ou sem sessão.
- **`POST /access-request`**, com `Depends(ses.mesma_origem)`. POST HTML comum,
  sem HTMX.
  - Sucesso (ou qualquer caso que deva parecer sucesso, seção 5): `303` para
    `/?requested=1#access`, que mostra a confirmação no lugar do formulário.
    Recarregar a página não reenvia.
  - Erro de validação: responde `422` com `landing.html` renderizada, o
    formulário com os valores preservados e os erros por campo.
  - Pedidos fechados (teto atingido): responde `503` com a landing mostrando o
    aviso no lugar do formulário.
- A landing **não** chama Steam, backpack.tf, cotação ou índice. O exemplo é
  estático; a página não depende de terceiros para responder.

## 5. Pedido de acesso

### Campos

| Campo | Nome no form | Regra |
| --- | --- | --- |
| Steam profile URL | `perfil_steam` | Obrigatório; ver normalização |
| Where can we reach you? | `contato` | Obrigatório; 1–200 caracteres após `strip` |
| Anything we should know? | `observacao` | Opcional; até 1000 caracteres após `strip`; vazio vira `NULL` |
| (honeypot) | `website` | Oculto de pessoas e de leitores de tela; deve vir vazio |

### Normalização do perfil da Steam

Aceita, com ou sem `https://`/`http://`, com ou sem `www.`, com ou sem barra
final:

- `steamcommunity.com/id/<nome>` — `<nome>` com 2–32 caracteres de
  `[A-Za-z0-9_-]`;
- `steamcommunity.com/profiles/<id>` — `<id>` com exatamente 17 dígitos.

Grava a forma canônica `https://steamcommunity.com/id/<nome>` ou
`https://steamcommunity.com/profiles/<id>`. O `<nome>` de `/id/` é comparado
em minúsculas (a Steam não diferencia) e gravado em minúsculas. Qualquer outra
entrada — outro host, caminho extra, query string — é erro de validação no
campo. A normalização é uma função pura, testável isoladamente.

### Respostas que não revelam estado

Todos estes casos respondem igual ao sucesso (`303` para a confirmação):

- honeypot preenchido — nada é gravado;
- já existe pedido **pendente** para o mesmo perfil canônico — nada é gravado.

Mensagem de confirmação (`role="status"`): *"Request filed. If approved, you'll
receive an invite link through the contact you gave."*

### Anti-spam

- **Limite por IP em memória:** no máximo 3 envios por IP por hora corrida
  (contam todos os envios que passam da validação de origem, gravados ou
  não). A chave junta todas as linhas do `X-Forwarded-For` e usa o último
  item — o que o Railway, único proxy na frente do app, acrescenta; a porta é
  removida, um IPv4 mapeado em IPv6 (`::ffff:1.2.3.4`) vira o IPv4 e um IPv6
  é agrupado pela rede `/64` que o contém. Sem o cabeçalho, a chave é o
  endereço da conexão. Com o cabeçalho presente mas o último item ilegível
  como IP, a chave cai num balde fixo único (`"invalido"`) em vez do
  `request.client.host` — falha fechado, porque sob
  `--forwarded-allow-ips=*` esse campo já foi reescrito pelo primeiro item,
  que o cliente controla. Um teto de 10 000 chaves na memória também falha
  fechado: uma vez cheio, chaves novas são recusadas (por até uma hora, até
  a mais antiga vencer), o que barra clientes legítimos novos mas impede que
  chaves forjadas cresçam sem limite. Ao exceder qualquer cota, `429` com a
  landing mostrando *"Too many requests from this connection. Try again
  later."* no lugar do formulário. O limitador recebe o relógio por injeção,
  protege seu estado com trava e descarta entradas vencidas. Vive na memória
  do processo, coerente com a regra atual de uma réplica só; um deploy o
  zera, o que o teto global cobre.
- **Teto global:** com 200 pedidos `pendente` ou mais, novos pedidos não são
  gravados e a página mostra *"Access requests are temporarily closed."*
- Ordem de checagem: limite por IP → honeypot → validação → teto global →
  deduplicação → insert. Honeypot, portanto, consome cota do IP (é o caso
  típico de robô), mas não grava.

### Tabela `pedido_acesso` (em `tf2price/db.py`)

| Coluna | Tipo | Observação |
| --- | --- | --- |
| `id` | Integer, PK | |
| `perfil_steam` | String(120), not null | forma canônica |
| `contato` | String(200), not null | |
| `observacao` | String(1000), null | |
| `criado_em` | DateTime, not null | UTC ingênuo (`db.agora()`) |
| `status` | String(20), not null | `pendente`, `convidado` ou `descartado` |
| `resolvido_em` | DateTime, null | preenchido ao convidar ou descartar |

Os limites de tamanho são validados no código antes do insert: o SQLite dos
testes não os impõe. A deduplicação de pendentes é feita por consulta dentro da
mesma transação curta do insert; uma corrida entre dois envios simultâneos do
mesmo perfil pode gerar duas linhas pendentes, o que é aceitável (o admin vê as
duas e descarta uma) e não justifica um índice parcial dependente de dialeto.

O SQL fica em um repositório novo em `tf2price/contas/` (os pedidos alimentam
convites), seguindo o padrão SQLAlchemy Core de `contas/repositorio.py`.

## 6. Case File de exemplo

- Reproduz os padrões visuais da avaliação real: veredito carimbado, colunas
  `THIS EFFECT` e `ALL EFFECTS` visualmente separadas, idade do preço à vista
  (*"priced 3 days ago"*) e valores em BRL.
- Selo fixo **SAMPLE CASE · FICTIONAL VALUES**, visível em todas as larguras.
- Só imagens **reais**, montadas como no palco da avaliação (`.evidence-visual`):
  a foto do Unusual Team Captain vinda do CDN da Steam (`url_da_imagem` com o
  `icon_url` fixo em `publico.ICONE_DO_EXEMPLO`, que o navegador carrega; o
  servidor não fala com a Steam) e três camadas da arte de efeito empacotada em
  `tf2price/data/efeitos/`, servida por `/arte/13.webp`. Nada de aura ou item
  desenhado para a landing.
- Veredito do exemplo: `Fair Price`.

## 7. Front-end

- `tf2price/painel/templates/landing.html`: template independente, não herda
  `base.html` (que traz a sidebar do app). Carrega `briefcase.css` (tokens,
  fontes locais, `.button`, foco) e `tf2price/painel/static/landing.css` (só o
  específico da landing).
- **Sem JavaScript.** Âncoras, formulário, erros e confirmação funcionam em
  HTML puro.
- O cartão do formulário reaproveita a linguagem de pasta de
  `auth_base.html`/`entrar.html` (aba "ACCESS FILE", papel, carimbo).
- `<title>`, `meta description` e Open Graph (título e descrição; sem
  `og:image`, porque o único logo disponível é SVG, que Discord e Steam não
  exibem como prévia) para uma boa prévia no Discord e na Steam.
- **Responsivo:** acima de ~900px, hero em duas colunas e cartão inclinado 2°;
  abaixo, uma coluna (texto → CTA → cartão sem rotação). Passos e colunas
  `THIS/ALL` empilham. O corpo nunca rola na horizontal.
- **Acessibilidade:** um único `h1`; seções com `h2` e `aria-labelledby`; skip
  link; `<label>` visível em cada campo; erro associado por
  `aria-describedby` e `aria-invalid`; após envio inválido, resumo de erros no
  topo do formulário com `tabindex="-1"` e âncora `#access` para levar o foco;
  alvos de toque de 44px; inclinação e transições desligadas em
  `prefers-reduced-motion`; contraste da paleta aprovada, com o ferrugem só em
  carimbo e CTA.

## 8. Administração

Nova seção **Access requests** em `/admin`, listando os pedidos `pendente` do
mais antigo para o mais novo: perfil como link externo
(`rel="noopener noreferrer"`, `target="_blank"`), contato, observação e
data de envio em UTC.
Todo texto vindo do pedido passa pelo autoescape do Jinja; o link do perfil só é
renderizado porque a forma canônica foi validada na entrada.

Ações (POST, `exigir_admin` + `mesma_origem`):

- **`POST /admin/pedido/{id}/convidar`** — chama `servico.convidar` já
  existente, marca o pedido como `convidado` com `resolvido_em` e mostra o link
  do convite onde ele aparece hoje, para o admin copiar e enviar. O token em
  claro continua existindo só nessa resposta.
- **`POST /admin/pedido/{id}/descartar`** — marca como `descartado` com
  `resolvido_em`.

Pedido inexistente ou já resolvido: a tela do admin volta com uma mensagem de
erro e nenhuma mudança. Convidar e marcar o pedido acontecem na mesma transação.

## 9. Testes (pytest, sem rede)

- `GET /` sem sessão → landing; com sessão → Overview; com `contexto=None` e sem
  sessão → landing (não depende de cotação nem índice).
- `normalizar_perfil_steam`: formas aceitas e canônicas; hosts, caminhos e
  tamanhos inválidos recusados.
- Pedido válido grava uma linha `pendente` com perfil canônico e `criado_em` do
  relógio.
- Perfil inválido, contato vazio ou longo demais, observação longa demais →
  `422`, nada gravado, valores preservados e erros por campo.
- Perfil com pedido pendente → mesma resposta de sucesso, sem linha nova.
- Honeypot preenchido → mesma resposta de sucesso, nada gravado.
- Quarto pedido do mesmo IP dentro de uma hora → `429`; após a janela, volta a
  aceitar (relógio injetado, sem `sleep`).
- Teto de pendentes atingido → `503` com aviso, nada gravado.
- `POST /access-request` com `Origin` de outro site → `403`.
- Admin: a seção só aparece para admin; `convidar` cria um convite válido, muda
  o status e mostra o link; `descartar` muda o status; ambos exigem mesma
  origem; pedido já resolvido não é alterado de novo.
- A tabela funciona sob o SQLite dos testes sem depender de semântica
  exclusiva de dialeto.

## 10. Documentação

Atualizar o `README.md`: a raiz pública passa a ser a landing, e os pedidos de
acesso aparecem em `/admin`.
