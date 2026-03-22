from pathlib import Path

p = Path("backend/main.py")
text = p.read_text(encoding="utf-8")

start = text.index('@app.post("/configs")')
end = text.index('@app.delete("/configs/{config_id}")')

new_block = '''@app.post("/configs")
async def create_config(
    name: str = Form(...),
    author: str = Form(...),
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
    allowed_types = {"legit", "closet", "blatant", "bedwars", "hypixel", "pvp", "outro"}
    if type not in allowed_types:
        raise HTTPException(status_code=400, detail="Tipo inválido")

    # Valida arquivo
    if not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Apenas arquivos .json")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB max
        raise HTTPException(status_code=400, detail="Arquivo muito grande (max 10MB)")

    # Valida JSON
    try:
        json.loads(content)
    except Exception:
        raise HTTPException(status_code=400, detail="Arquivo JSON inválido")

    # Upload GitHub
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    safe_name = sanitize_text(name, 50).replace(" ", "_")
    filename = f"{timestamp}-{safe_name}-by-{sanitize_text(author, 30)}.json"
    file_url = await upload_to_github(filename, content)

    # Salva no banco via ORM (parameterizado — seguro)
    data = {
        "name": sanitize_text(name, 100),
        "author": sanitize_text(author, 80),
        "type": type,
        "desc": sanitize_text(desc, 500),
        "file_url": file_url,
        "server": sanitize_text(server, 50),
        "user_id": str(user.id),
    }
    try:
        # Usa service role no backend para evitar bloqueio por RLS
        # (permissões de negócio já são validadas acima)
        res = supabase_admin.table("configs").insert(data).execute()
        return {"config": res.data[0]}
    except Exception:
        raise HTTPException(status_code=500, detail="Erro ao salvar config no banco")

'''

text = text[:start] + new_block + text[end:]
p.write_text(text, encoding="utf-8")

print("✅ Bloco create_config reescrito com indentação limpa.")