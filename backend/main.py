from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import httpx
import os
import base64
import json
from datetime import datetime
from typing import Optional
import supabase as sb
from supabase import create_client, Client
from dotenv import load_dotenv
import uuid
load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

security = HTTPBearer()

app = FastAPI(title="OpenConfigs API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_supabase_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Valida o JWT do Supabase e retorna o usuário."""
    token = credentials.credentials
    try:
        user = supabase.auth.get_user(token)
        if not user or not user.user:
            raise HTTPException(status_code=401, detail="Token inválido")
        return user.user
    except Exception:
        raise HTTPException(status_code=401, detail="Não autorizado")

def require_admin(user=Depends(get_supabase_user)):
    """Garante que o usuário é admin."""
    if user.email != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Acesso negado")
    return user

import re

def sanitize_text(value: str, max_len: int = 50) -> str:
    if not value:
        return "config"

    value = value.lower()
    value = re.sub(r'[^\w\s-]', '', value)
    value = value.strip().replace(" ", "_")

    return value[:max_len] or "config"
    
async def upload_to_github(filename: str, content: bytes) -> str:
    """Faz upload do .json para o GitHub e retorna a URL raw."""
    path = f"configs/{filename}"
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    encoded = base64.b64encode(content).decode()

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    # Verifica se já existe (pra pegar o sha)
    sha = None
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers)
        if r.status_code == 200:
            sha = r.json().get("sha")

        payload = {
            "message": f"upload config: {filename}",
            "content": encoded,
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

        r = await client.put(url, headers=headers, json=payload)
        if r.status_code not in (200, 201):
            raise HTTPException(status_code=500, detail="Erro ao enviar para o GitHub")

    raw_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{path}"
    return raw_url

# ── Auth Routes ───────────────────────────────────────────────────────────────

@app.post("/auth/verify-otp")
async def verify_otp(request: Request):
    body = await request.json()
    email = body.get("email", "").strip()
    token = body.get("token", "").strip()  # código 6 dígitos

    if not email or not token:
        raise HTTPException(status_code=400, detail="Email e código obrigatórios")

    try:
        res = supabase.auth.verify_otp({
            "email": email,
            "token": token,
            "type": "signup"  # ou "email" pra login sem senha
        })
        return {
            "access_token": res.session.access_token,
            "user": {
                "id": res.user.id,
                "email": res.user.email,
                "is_admin": res.user.email == ADMIN_EMAIL,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail="Código inválido ou expirado")

@app.post("/auth/register")
async def register(request: Request):
    body = await request.json()
    email = body.get("email", "").strip()  # ✅ sem sanitize_text
    password = body.get("password", "")
    
    if not email or not password or len(password) < 8:
        raise HTTPException(status_code=400, detail="Email ou senha inválidos")

    try:
        print("EMAIL RECEBIDO:", repr(email))
        res = supabase.auth.sign_up({"email": email, "password": password})
        return {"message": "Verifique seu email para confirmar o cadastro!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/auth/login")
async def login(request: Request):
    """Login com email + senha."""
    body = await request.json()
    email = body.get("email", "").strip()
    password = body.get("password", "")

    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        return {
            "access_token": res.session.access_token,
            "user": {
                "id": res.user.id,
                "email": res.user.email,
                "is_admin": res.user.email == ADMIN_EMAIL,
            }
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Email ou senha incorretos")

@app.post("/auth/logout")
async def logout(user=Depends(get_supabase_user)):
    supabase.auth.sign_out()
    return {"message": "Logout realizado"}

# ── Config Routes ─────────────────────────────────────────────────────────────

@app.get("/configs")
async def list_configs(
    search: Optional[str] = None,
    type: Optional[str] = None,
    client: Optional[str] = None,
    author: Optional[str] = None,
    name: Optional[str] = None,
    server: Optional[str] = None,
):
    """Lista configs públicas. Usa parâmetros — sem concatenação de string."""
    # Usa service role para leitura pública independente de políticas RLS
    query = supabase_admin.table("configs").select("*").order("created_at", desc=True)

    # Filtros via ORM do Supabase (sem SQL cru — seguro contra injection)
    if type and type != "all":
        query = query.eq("type", sanitize_text(type, 50))
    if client and client != "all":
        query = query.eq("client", sanitize_text(client, 50))
    if server and server != "all":
        query = query.eq("server", sanitize_text(server, 50))
    if author:
        query = query.ilike("author", f"%{sanitize_text(author, 80)}%")
    if name:
        query = query.ilike("name", f"%{sanitize_text(name, 100)}%")
    if search:
        clean_search = sanitize_text(search, 100)
        query = query.or_(f"name.ilike.%{clean_search}%,author.ilike.%{clean_search}%,desc.ilike.%{clean_search}%")

    res = query.execute()
    return {"configs": res.data}

@app.post("/configs")
async def create_config(
    name: str = Form(...),
    author: str = Form(...),
    client: str = Form(...),
    type: str = Form(...),
    desc: str = Form(""),
    server: str = Form("outro"),
    file: UploadFile = File(...),
    user=Depends(get_supabase_user),
):
    """Cria config. Usuário precisa estar logado e com email confirmado."""
    # Verifica email confirmado
    if not user.email_confirmed_at:
        raise HTTPException(status_code=403, detail="Confirme seu email primeiro")

    # Valida tipo
    allowed_types = {"legit", "blatant", "ghost"}
    if type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo inválido")

    # Valida client
allowed_clients = {
    "augustus", "astolfo", "slinky", "myau", "myau+",
    "avocado", "vestigereborn", "liquidbounce", "velarion",
    "catlean", "mio", "doomsday"
}

if sanitize_text(client, 50).lower() not in allowed_clients:
    raise HTTPException(status_code=400, detail="Client inválido")

if sanitize_text(client, 50).lower() not in allowed_clients:
    raise HTTPException(status_code=400, detail="Client inválido")

    # Valida arquivo (.json/.txt)
    if not (file.filename.endswith(".json") or file.filename.endswith(".txt")):
        raise HTTPException(status_code=400, detail="Apenas arquivos .json ou .txt")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB max
        raise HTTPException(status_code=400, detail="Arquivo muito grande (max 10MB)")

    # Valida JSON apenas quando for .json
    if file.filename.endswith(".json"):
        try:
            json.loads(content)
        except Exception:
            raise HTTPException(status_code=400, detail="Arquivo JSON inválido")

    # Upload GitHub
    import uuid

    safe_name = sanitize_text(name)
    uid = uuid.uuid4().hex[:2]

    filename = f"{safe_name}-{client}-{uid}.json"
    ext = ".txt" if file.filename.endswith(".txt") else ".json"
    file_url = await upload_to_github(filename, content)

    # Salva no banco via ORM (parameterizado — seguro)
    data = {
        "name": sanitize_text(name, 100),
        "author": sanitize_text(author, 80),
        "client": sanitize_text(client, 50),
        "type": type,
        "desc": sanitize_text(desc, 500),
        "file_url": file_url,
        "server": sanitize_text(server, 50),
        "user_id": str(user.id),
    }

    try:
        # Usa service role no backend para evitar bloqueio por RLS
        res = supabase_admin.table("configs").insert(data).execute()
        return {"config": res.data[0]}
    except Exception:
        raise HTTPException(status_code=500, detail="Erro ao salvar config no banco")

@app.delete("/configs/{config_id}")
async def delete_config(config_id: int, user=Depends(get_supabase_user)):
    """Deleta config — só o dono ou admin."""
    res = supabase_admin.table("configs").select("*").eq("id", config_id).execute()
    res = supabase_admin.table("configs").select("*").eq("id", config_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Config não encontrada")

    cfg = res.data[0]
    is_admin = user.email == ADMIN_EMAIL
    is_owner = cfg.get("user_id") == str(user.id)

    if not is_admin and not is_owner:
        raise HTTPException(status_code=403, detail="Sem permissão")

    supabase_admin.table("configs").delete().eq("id", config_id).execute()
    supabase_admin.table("configs").delete().eq("id", config_id).execute()
    return {"message": "Config deletada"}

# ── Admin Routes ──────────────────────────────────────────────────────────────

@app.get("/admin/users")
async def list_users(admin=Depends(require_admin)):
    """Lista todos os usuários (só admin)."""
    res = supabase_admin.auth.admin.list_users()
    users = [{"id": u.id, "email": u.email, "confirmed": u.email_confirmed_at is not None} for u in res]
    return {"users": users}


@app.get("/me/configs")
async def my_configs(user=Depends(get_supabase_user)):
    """Lista configs do usuário logado."""
    res = supabase_admin.table("configs").select("*").eq("user_id", str(user.id)).order("created_at", desc=True).execute()
    return {"configs": res.data}

@app.delete("/admin/configs/{config_id}")
async def admin_delete_config(config_id: int, admin=Depends(require_admin)):
    """Admin deleta qualquer config."""
    supabase_admin.table("configs").delete().eq("id", config_id).execute()
    supabase_admin.table("configs").delete().eq("id", config_id).execute()
    return {"message": "Config deletada pelo admin"}

@app.get("/admin/stats")
async def admin_stats(admin=Depends(require_admin)):
    """Estatísticas gerais."""
    configs = supabase.table("configs").select("type").execute()
    total = len(configs.data)
    by_type = {}
    for c in configs.data:
        by_type[c["type"]] = by_type.get(c["type"], 0) + 1
    return {"total_configs": total, "by_type": by_type}

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
