from pathlib import Path
import re

ROOT = Path(".")
BACKEND = ROOT / "backend" / "main.py"
FRONTEND = ROOT / "frontend" / "index.html"
ROOT_VERCEL = ROOT / "vercel.json"
FRONTEND_VERCEL = ROOT / "frontend" / "vercel.json"
ROOT_MAIN = ROOT / "main.py"

def must_read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    return path.read_text(encoding="utf-8")

def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def patch_backend():
    text = must_read(BACKEND)

    # 1) list_configs assinatura + filtros novos + supabase_admin
    pattern_list = re.compile(
        r'@app\.get\("/configs"\)\s*'
        r'async def list_configs\([^\)]*\):\s*'
        r'"""Lista configs públicas\. Usa parâmetros — sem concatenação de string\."""'
        r'[\s\S]*?'
        r'return \{"configs": res\.data\}',
        re.MULTILINE
    )

    replacement_list = '''@app.get("/configs")
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
    return {"configs": res.data}'''

    text, n1 = pattern_list.subn(replacement_list, text, count=1)
    if n1 == 0:
        raise RuntimeError("Não consegui localizar/substituir bloco list_configs em backend/main.py")

    # 2) create_config assinatura e corpo (bloco inteiro)
    pattern_create = re.compile(
        r'@app\.post\("/configs"\)\s*'
        r'async def create_config\([\s\S]*?\):'
        r'[\s\S]*?'
        r'(?=@app\.delete\("/configs/\{config_id\}"\))',
        re.MULTILINE
    )

    replacement_create = '''@app.post("/configs")
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
    allowed_clients = {"augustus", "astolfo", "slinky", "myau", "myau+", "avocado", "vestigereborn"}
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
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    safe_name = sanitize_text(name, 50).replace(" ", "_")
    ext = ".txt" if file.filename.endswith(".txt") else ".json"
    filename = f"{timestamp}-{safe_name}-by-{sanitize_text(author, 30)}{ext}"
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

'''

    text, n2 = pattern_create.subn(replacement_create, text, count=1)
    if n2 == 0:
        raise RuntimeError("Não consegui localizar/substituir bloco create_config em backend/main.py")

    # 3) garante supabase_admin em delete_config / admin_delete_config
    text = text.replace(
        'res = supabase.table("configs").select("*").eq("id", config_id).execute()',
        'res = supabase_admin.table("configs").select("*").eq("id", config_id).execute()'
    )
    text = text.replace(
        'supabase.table("configs").delete().eq("id", config_id).execute()',
        'supabase_admin.table("configs").delete().eq("id", config_id).execute()'
    )

    # 4) adiciona /me/configs se não existir
    if '@app.get("/me/configs")' not in text:
        anchor = '@app.delete("/admin/configs/{config_id}")'
        idx = text.find(anchor)
        if idx == -1:
            raise RuntimeError("Não encontrei âncora para inserir /me/configs no backend/main.py")
        insert_block = '''
@app.get("/me/configs")
async def my_configs(user=Depends(get_supabase_user)):
    """Lista configs do usuário logado."""
    res = supabase_admin.table("configs").select("*").eq("user_id", str(user.id)).order("created_at", desc=True).execute()
    return {"configs": res.data}

'''
        text = text[:idx] + insert_block + text[idx:]

    write(BACKEND, text)

def patch_frontend():
    html = must_read(FRONTEND)

    # API relative
    html = html.replace(
        "const API = 'https://sitecloud-production.up.railway.app';",
        "const API = '/api';"
    )

    # Header buttons download/perfil
    html = html.replace(
        '''    <div id="hauth">
      <button class="btn btn-o btn-sm" onclick="openAuth()">LOGIN</button>
      <button class="btn btn-g btn-sm" onclick="openAuth('register')">CADASTRAR</button>
    </div>''',
        '''    <button class="btn btn-o btn-sm" onclick="openDL()">DOWNLOAD</button>
    <button class="btn btn-o btn-sm" onclick="openProfile()">PERFIL</button>
    <div id="hauth">
      <button class="btn btn-o btn-sm" onclick="openAuth()">LOGIN</button>
      <button class="btn btn-g btn-sm" onclick="openAuth('register')">CADASTRAR</button>
    </div>'''
    )

    # Servers include "outro"
    html = html.replace(
        '''  <div class="srv srv-kaizen" onclick="toggleSrv('kaizen',this)"> Kaizen</div>
</div>''',
        '''  <div class="srv srv-kaizen" onclick="toggleSrv('kaizen',this)"> Kaizen</div>
  <div class="srv" onclick="toggleSrv('outro',this)"> Outro</div>
</div>'''
    )

    # Controls block
    html = html.replace(
        '''<div class="controls">
  <div class="sw">
    <span class="si">//</span>
    <input type="text" id="si" placeholder="buscar config, autor..." oninput="deb()">
  </div>
  <div class="ftags">
    <span class="ft on" onclick="setF('all',this)">Todas</span>
    <span class="ft" onclick="setF('legit',this)">Legit</span>
    <span class="ft" onclick="setF('closet',this)">Closet</span>
    <span class="ft" onclick="setF('blatant',this)">Blatant</span>
    <span class="ft" onclick="setF('bedwars',this)">BedWars</span>
    <span class="ft" onclick="setF('pvp',this)">PvP</span>
  </div>
</div>''',
        '''<div class="controls">
  <div class="sw">
    <span class="si">//</span>
    <input type="text" id="si" placeholder="buscar nome/autor/descrição..." oninput="deb()">
  </div>
  <div class="fg" style="max-width:460px;margin:8px auto 0">
    <label>Client</label>
    <select id="clientFilter" onchange="load()">
      <option value="all">Todos</option><option value="augustus">Augustus</option><option value="astolfo">Astolfo</option><option value="slinky">Slinky</option><option value="myau">Myau</option><option value="myau+">Myau+</option><option value="avocado">Avocado</option><option value="vestigereborn">VestigeReborn</option>
    </select>
  </div>
  <div class="fg" style="max-width:460px;margin:8px auto 0">
    <label>Formato</label>
    <select id="extFilter" onchange="load()"><option value="all">Todos</option><option value="json">JSON</option><option value="txt">TXT</option></select>
  </div>
  <div class="ftags">
    <span class="ft on" onclick="setF('all',this)">Todas</span>
    <span class="ft" onclick="setF('legit',this)">Legit</span>
    <span class="ft" onclick="setF('blatant',this)">Blatant</span>
    <span class="ft" onclick="setF('ghost',this)">Ghost</span>
  </div>
</div>'''
    )

    # Upload selects
    html = html.replace(
        '''    <div class="fg"><label>Tipo</label>
      <select id="uT"><option value="legit">Legit</option><option value="closet">Closet</option><option value="blatant">Blatant</option><option value="pvp">PvP</option><option value="bedwars">BedWars</option><option value="outro">Outro</option></select>
    </div>''',
        '''    <div class="fg"><label>Client</label>
      <select id="uC"><option value="augustus">Augustus</option><option value="astolfo">Astolfo</option><option value="slinky">Slinky</option><option value="myau">Myau</option><option value="myau+">Myau+</option><option value="avocado">Avocado</option><option value="vestigereborn">VestigeReborn</option></select>
    </div>
    <div class="fg"><label>Tipo</label>
      <select id="uT"><option value="legit">Legit</option><option value="blatant">Blatant</option><option value="ghost">Ghost</option></select>
    </div>'''
    )

    html = html.replace('<label>Arquivo .json</label>', '<label>Arquivo .json/.txt</label>')
    html = html.replace(
        '<input type="file" id="fileInput" accept=".json" onchange="hFile(this)">',
        '<input type="file" id="fileInput" accept=".json,.txt" onchange="hFile(this)">'
    )

    # Add modals profile/download
    html = html.replace(
        '<div class="toast" id="toast"></div>',
        '''<!-- PROFILE -->
<div class="ov" id="profOv">
  <div class="modal" style="max-width:760px">
    <div class="mh"><div class="mt">MEU PERFIL</div><button class="mc" onclick="closeProfile()">✕</button></div>
    <div id="profList" class="al"></div>
  </div>
</div>

<!-- DOWNLOADS -->
<div class="ov" id="dlOv">
  <div class="modal" style="max-width:760px">
    <div class="mh"><div class="mt">DOWNLOADS</div><button class="mc" onclick="closeDL()">✕</button></div>
    <div class="al" id="dlList"></div>
  </div>
</div>

<div class="toast" id="toast"></div>'''
    )

    # JS adjustments
    html = html.replace(
        "const TC = {legit:'t-legit',closet:'t-closet',blatant:'t-blatant',bedwars:'t-bedwars',pvp:'t-pvp',outro:'t-outro'};",
        "const TC = {legit:'t-legit',blatant:'t-blatant',ghost:'t-closet'};"
    )

    html = html.replace(
        '''async function load(){
  const q=document.getElementById('si').value;
  let url='/configs?';
  if(filter!=='all')url+=`type=${filter}&`;
  if(q)url+=`search=${encodeURIComponent(q)}`;
  try{
    const d=await api('GET',url);
    let list=d.configs||[];
    if(srvFilter)list=list.filter(c=>c.server===srvFilter);
    render(list);
    const tot=d.configs?.length||0;''',
        '''async function load(){
  const q=document.getElementById('si').value;
  const client=document.getElementById('clientFilter')?.value||'all';
  const ext=document.getElementById('extFilter')?.value||'all';
  let url='/configs?';
  if(filter!=='all')url+=`type=${filter}&`;
  if(client!=='all')url+=`client=${encodeURIComponent(client)}&`;
  if(srvFilter)url+=`server=${encodeURIComponent(srvFilter)}&`;
  if(q)url+=`search=${encodeURIComponent(q)}`;
  try{
    const d=await api('GET',url);
    let list=d.configs||[];
    if(ext!=='all')list=list.filter(c=>(c.file_url||'').toLowerCase().endsWith('.'+ext));
    render(list);
    const tot=list.length||0;'''
    )

    html = html.replace(
        "const stag=c.server?`<span class=\"stag ${sc}\">${se} ${c.server}</span>`:'';",
        "const stag=c.server?`<span class=\"stag ${sc}\">${se} ${c.server}</span>`:'';\n    const ctag=c.client?`<span class=\"stag\">${esc(c.client)}</span>`:'';"
    )
    html = html.replace(
        '<div class="cm">${desc}<div class="ctags">${stag}</div></div>',
        '<div class="cm">${desc}<div class="ctags">${ctag}${stag}</div></div>'
    )

    html = html.replace(
        "if(f?.name.endsWith('.json')){uFile=f;document.getElementById('fn').textContent='📎 '+f.name;}else showToast('⚠ Apenas .json!',true);",
        "if(f&&(/\\.(json|txt)$/i).test(f.name)){uFile=f;document.getElementById('fn').textContent='📎 '+f.name;}else showToast('⚠ Apenas .json ou .txt!',true);"
    )

    html = html.replace(
        '''async function submit(){
  const n=document.getElementById('uN').value.trim(),a=document.getElementById('uA').value.trim(),t=document.getElementById('uT').value,s=document.getElementById('uS').value,d=document.getElementById('uD').value.trim();
  if(!n||!a)return setUA('Preencha nome e nick');
  if(!uFile)return setUA('Selecione um .json');''',
        '''async function submit(){
  const n=document.getElementById('uN').value.trim(),a=document.getElementById('uA').value.trim(),c=document.getElementById('uC').value,t=document.getElementById('uT').value,s=document.getElementById('uS').value,d=document.getElementById('uD').value.trim();
  if(!n||!a)return setUA('Preencha nome e nick');
  if(!uFile)return setUA('Selecione um .json/.txt');'''
    )

    html = html.replace(
        "form.append('name',n);form.append('author',a);form.append('type',t);form.append('server',s);",
        "form.append('name',n);form.append('author',a);form.append('client',c);form.append('type',t);form.append('server',s);"
    )

    # inject JS helper functions at end
    marker = "function setUA(msg){document.getElementById('upAlert').innerHTML=`<div class=\"ab ab-err\">${esc(msg)}</div>`;}"
    addon = '''
function openProfile(){if(!user){openAuth();return;}document.getElementById('profOv').classList.add('open');loadProfile();}
function closeProfile(){document.getElementById('profOv').classList.remove('open');}
document.getElementById('profOv').addEventListener('click',e=>{if(e.target===e.currentTarget)closeProfile();});
async function loadProfile(){
  try{
    const d=await api('GET','/me/configs');
    const list=d.configs||[];
    document.getElementById('profList').innerHTML=list.length?list.map(c=>`<div class="ar"><div class="ar-info"><div class="ar-name">${esc(c.name||'sem-nome')}</div><div class="ar-by">${esc(c.client||'client')} · ${esc(c.type||'tipo')} · ${esc((c.created_at||'').split('T')[0])}</div></div><a class="btn btn-g btn-sm" href="${esc(c.file_url)}" target="_blank">ABRIR</a></div>`).join(''):'<div class="empty"><p>Você ainda não publicou configs.</p></div>';
  }catch(e){showToast('Erro perfil: '+e.message,true);}
}

function openDL(){document.getElementById('dlOv').classList.add('open');renderDL();}
function closeDL(){document.getElementById('dlOv').classList.remove('open');}
document.getElementById('dlOv').addEventListener('click',e=>{if(e.target===e.currentTarget)closeDL();});
function renderDL(){
  const links=[
    ['Slinky','https://www.mediafire.com/file/1o209cxbzkpz58i/slinkyload.zip/file'],
    ['Myau','https://www.mediafire.com/file/h7usx9o2s98wd4z/MYAU.jar/file'],
    ['Astolfo','https://www.mediafire.com/file/18xq7e4wij0ox4j/Astolfo-LATEST.zip/file'],
    ['Augustus (CrackCrew{cc})','https://www.mediafire.com/file/n43lmn7p7c8as4b/Augustus.zip/file'],
    ['Myau+','https://github.com/IamNespola/OpenMyau-Plus/releases'],
    ['Avocado','https://www.mediafire.com/file/qc76zztrq689c6m/avocado-b1.5.jar/file'],
    ['VestigeR','https://www.mediafire.com/file/ieny7lgmzc7hglq/VestigeR+1.1.0-1.zip/file']
  ];
  document.getElementById('dlList').innerHTML=links.map(([n,u])=>`<div class="ar"><div class="ar-info"><div class="ar-name">${esc(n)}</div><div class="ar-by">Link oficial</div></div><a class="btn btn-g btn-sm" href="${esc(u)}" target="_blank">DOWNLOAD</a></div>`).join('');
}'''
    if marker in html and "function openProfile()" not in html:
        html = html.replace(marker, marker + "\n" + addon)

    write(FRONTEND, html)

def write_configs():
    write(ROOT_MAIN, '"""Entrypoint para deploys que usam `uvicorn main:app`."""\n\nfrom backend.main import app\n')

    write(ROOT_VERCEL, '''{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://sitecloud-production.up.railway.app/:path*" },
    { "source": "/(.*)", "destination": "/frontend/index.html" }
  ]
}
''')

    write(FRONTEND_VERCEL, '''{
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://sitecloud-production.up.railway.app/:path*" },
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
''')

def main():
    patch_backend()
    patch_frontend()
    write_configs()
    print("✅ apply_fix_all concluído com sucesso.")

if __name__ == "__main__":
    main()