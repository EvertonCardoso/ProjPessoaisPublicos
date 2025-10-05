# Download de Vídeos (TikTok / YouTube / Instagram / Facebook)

Aplicação Flask em Docker para baixar vídeos (preferindo MP4) a partir de **TikTok, YouTube, Instagram e Facebook**.  
A interface web aceita **URL**, permite informar **cookies** (quando a plataforma exige login) e exibe **progresso em tempo real** via SSE.  
O container faz **limpeza diária** da pasta `downloads/` às **00:01**.

> **Atenção legal**: use somente para conteúdos que você tem **direito de baixar** (seus próprios vídeos, conteúdos com licença, etc.). Respeite os Termos das plataformas e leis de copyright.

---

## ✨ Recursos

- ✅ Suporte a **TikTok, YouTube, Instagram e Facebook**
- ✅ Preferência por **MP4** (merge de vídeo+áudio com `ffmpeg`)
- ✅ **Progresso** (%/velocidade/ETA) via **SSE** na UI
- ✅ Upload de **cookies.txt** (formato Netscape) **ou** colagem de **Cookie Header**
- ✅ **Limpeza automática** de `downloads/` todos os dias às **00:01**
- ✅ Execução com **gunicorn** (produção simples) atrás do Docker
- ✅ Layout escuro, responsivo, logo customizável em `static/`

---

## 🧱 Stack

- **Python 3.12**, **Flask**, **gunicorn**
- **yt-dlp** (download/extração) + **ffmpeg** (merge/conversão)
- **Docker** + **Docker Compose**
- **Server‑Sent Events** para progresso

---

## 📁 Estrutura (sugerida)

```
.
├─ Dockerfile
├─ docker-compose.yml
├─ requirements.txt
├─ app.py
├─ templates/
│  └─ index.html
├─ static/
│  └─ angeloni_logo_white.png
├─ downloads/           # (criada/limpa automaticamente no container)
└─ cookies/             # cookies.txt (Netscape) – NÃO versionar
```

> `.gitignore` recomendado:
```
downloads/
cookies/
__pycache__/
*.pyc
*.log
.venv/
venv/
.DS_Store
```

---

## ⚙️ Pré‑requisitos

- **Docker** e **Docker Compose** instalados
- Porta **8085** livre (ou mapeie para outra)
- (Opcional) `cookies/cookies.txt` para conteúdos que exigem login

---

## 🚀 Subir com Docker Compose (rápido)

1. Crie o `docker-compose.yml` (exemplo):
   ```yaml
   services:
     web:
       build: .
       image: downloadvideos-web
       container_name: downloadvideos-web
       ports:
         - "8085:8085"               # Altere a porta externa se 8085 estiver em uso
       environment:
         - TZ=America/Sao_Paulo
       volumes:
         - ./downloads:/app/downloads
         - ./cookies:/app/cookies
         - ./static:/app/static      # opcional (logo/estáticos)
         - ./templates:/app/templates # opcional (customizar UI)
       restart: unless-stopped
   ```

2. **Build + up**:
   ```bash
   docker compose build --no-cache
   docker compose up -d
   ```

3. Abra **http://localhost:8085** no navegador.

> Para acompanhar logs em tempo real:
```bash
docker compose logs -f
```

---

## 🔑 Cookies (quando pedem login)

Alguns vídeos (especialmente **TikTok/Instagram/Facebook**) podem exigir autenticação. Use **uma** das opções:

### A) `cookies.txt` (formato Netscape)
- Exporte via uma extensão (Cookie‑Editor) ou script e salve como `cookies/cookies.txt`.
- **Monte** a pasta `./cookies` no container (já previsto no `compose`).  
- Carregue o arquivo pela UI **ou** deixe em `./cookies/cookies.txt` (é detectado automaticamente).

### B) **Cookie Header** (rápido)
- Abra o DevTools (**F12**) → **Network** → selecione uma requisição para `tiktok.com`/`instagram.com`/`facebook.com`
- Em **Headers** → **Request Headers**, copie o valor inteiro de **`Cookie`** e **cole na UI**.

> Dica: garanta que a sessão está **ativa** e que o cookie tem os campos de sessão (ex.: `sessionid`, `sid_guard`, `ttwid`, `datr`, `c_user`, etc.).

---

## 📊 Progresso

A UI abre um canal **SSE** (`/progress/<job_id>`) que recebe mensagens de progresso do `yt-dlp` (percentual, velocidade e ETA).  
Ao terminar, o navegador baixa o arquivo de **`/result/<job_id>`** com o **nome correto**.

---

## 🧹 Limpeza diária (00:01)

O container executa uma **tarefa diária** às **00:01** para **esvaziar** `downloads/`.  
Se quiser manter seus arquivos, **copie-os** para fora da pasta `downloads/` ou remova/ajuste a rotina no Dockerfile/entrypoint.

---

## 🛠️ Desenvolvimento local (sem Docker)

> Requer `ffmpeg` instalado no sistema.

```bash
python -m venv .venv
source .venv/bin/activate            # Linux/macOS
# .venv\Scripts\Activate.ps1         # Windows PowerShell

pip install -r requirements.txt
export FLASK_ENV=development
python app.py                        # roda em 0.0.0.0:8085
```

Para produção, preferir `gunicorn`:
```bash
gunicorn -b 0.0.0.0:8085 -w 2 --threads 4 --timeout 120 app:app
```

---

## ♻️ Atualizar `yt-dlp`

Algumas quebras de site são corrigidas rapidamente no `yt-dlp`. Para atualizar:

- **Rebuild da imagem** (pinned no `requirements.txt`):
  ```bash
  docker compose build --no-cache
  docker compose up -d
  ```

- **Ou dentro do container** (temporário):
  ```bash
  docker exec -it downloadvideos-web sh -lc "pip install -U yt-dlp && yt-dlp --version"
  docker compose restart
  ```

> Se o nome do container for outro, ajuste o comando (`docker ps`).

---

## 🧩 Solução de problemas

- **Porta 8085 já em uso**  
  ```bash
  docker ps --format 'table {{.ID}}\t{{.Image}}\t{{.Ports}}'
  # ou
  ss -ltnp | grep :8085
  ```
  Edite o `docker-compose.yml` e mude para `"9090:8085"` ou pare o serviço conflitante.

- **“Requiring login / use --cookies”**  
  Cookies inválidos/ausentes. Refaça o export de `cookies.txt` ou cole o **Cookie Header** válido.

- **“Arquivo não encontrado após o download”**  
  Em geral é `yt-dlp` + mudanças no site. Tente **atualizar `yt-dlp`** e/ou testar com cookies válidos.

- **Sem progresso na UI**  
  Proxies corporativos podem bloquear SSE. Teste localmente sem proxy ou ajuste reverse proxy (desabilite buffering).

- **Logo não aparece**  
  Confirme que o arquivo está em `static/angeloni_logo_white.png` e que a pasta está montada no container (se estiver usando bind mount).

---

## 🔒 Boas práticas

- **Não** versione `cookies/` e `downloads/` (use `.gitignore`).
- **Atualize `yt-dlp`** ao notar erros de extração.
- **Limite de uso**: baixe apenas conteúdos com **direito** de uso.
- **Ambiente**: use `gunicorn` no container; não ative `debug` em produção.
- **Observabilidade**: use `docker compose logs -f` para diagnosticar.  
- **Recursos**: se baixar muitos vídeos grandes, considere aumentar `--timeout`/`--threads` do `gunicorn`.

---

## 🧾 Licença

Escolha a licença que preferir (ex.: MIT) e crie um arquivo `LICENSE` no repositório.

---

## 👨‍💻 Créditos

Desenvolvido por **Everton Cardoso Deolinda** – [LinkedIn](https://www.linkedin.com/in/everton-cardoso-deolinda-2853861b2/).
