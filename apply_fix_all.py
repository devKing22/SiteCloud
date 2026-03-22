from pathlib import Path
from datetime import datetime

ROOT = Path(".")
BACKEND = ROOT / "backend" / "main.py"
FRONT = ROOT / "frontend" / "index.html"
MIG = ROOT / "backend" / "migrations" / f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_config_heaven.sql"

def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

def patch_sql():
    sql = """
-- ===========================
-- Config Heaven migration
-- ===========================

-- configs extras
alter table if exists configs
  add column if not exists client text,
  add column if not exists server text,
  add column if not exists views bigint default 0;

-- profile username fields (na tabela de usuários da app)
create table if not exists profiles (
  user_id text primary key,
  username text unique,
  username_changed_at timestamptz default now()
);

-- reviews por config (1..5)
create table if not exists config_reviews (
  id bigserial primary key,
  config_id bigint not null,
  user_id text not null,
  stars int not null check (stars >= 1 and stars <= 5),
  created_at timestamptz default now(),
  unique(config_id, user_id)
);

-- comments por config
create table if not exists config_comments (
  id bigserial primary key,
  config_id bigint not null,
  user_id text not null,
  author text not null,
  comment text not null,
  created_at timestamptz default now()
);

create index if not exists idx_config_reviews_config_id on config_reviews(config_id);
create index if not exists idx_config_comments_config_id on config_comments(config_id);
"""
    write(MIG, sql.strip() + "\n")

def patch_backend():
    text = BACKEND.read_text(encoding="utf-8")

    # Nome do site/API
    text = text.replace('FastAPI(title="OpenConfigs API", version="1.0.0")',
                        'FastAPI(title="Config Heaven API", version="2.0.0")')

    # allowed types
    text = text.replace(
        'allowed_types = {"legit", "blatant", "ghost"}',
        'allowed_types = {"legit", "blatant", "ghost"}'
    )

    # allowed clients completo
    text = text.replace(
        'allowed_clients = {"augustus", "astolfo", "slinky", "myau", "myau+", "avocado", "vestigereborn"}',
        'allowed_clients = {"augustus", "astolfo", "slinky", "myau", "myau+", "avocado", "vestigereborn", "doomsday", "haru", "elixe", "liquidbounce", "sigma5", "sigma4.11", "ravenb-", "biggie", "exhibition"}'
    )

    # Inserir endpoints extras se não existirem
    if '@app.post("/configs/{config_id}/view")' not in text:
        text += """

@app.post("/configs/{config_id}/view")
async def add_view(config_id: int):
    row = supabase_admin.table("configs").select("id,views").eq("id", config_id).execute()
    if not row.data:
        raise HTTPException(status_code=404, detail="Config não encontrada")
    current = row.data[0].get("views") or 0
    supabase_admin.table("configs").update({"views": current + 1}).eq("id", config_id).execute()
    return {"views": current + 1}

@app.get("/configs/{config_id}/reviews")
async def get_reviews(config_id: int):
    rv = supabase_admin.table("config_reviews").select("*").eq("config_id", config_id).execute()
    cm = supabase_admin.table("config_comments").select("*").eq("config_id", config_id).order("created_at", desc=True).execute()
    stars = [r["stars"] for r in rv.data] if rv.data else []
    avg = (sum(stars) / len(stars)) if stars else 0
    return {"avg": avg, "count": len(stars), "comments": cm.data or []}

@app.post("/configs/{config_id}/reviews")
async def upsert_review(
    config_id: int,
    request: Request,
    user=Depends(get_supabase_user)
):
    body = await request.json()
    stars = int(body.get("stars", 0))
    comment = sanitize_text(body.get("comment", ""), 500)

    if stars < 1 or stars > 5:
        raise HTTPException(status_code=400, detail="Stars deve ser entre 1 e 5")

    payload = {"config_id": config_id, "user_id": str(user.id), "stars": stars}
    supabase_admin.table("config_reviews").upsert(payload, on_conflict="config_id,user_id").execute()

    if comment:
        supabase_admin.table("config_comments").insert({
            "config_id": config_id,
            "user_id": str(user.id),
            "author": user.email.split("@")[0] if user.email else "user",
            "comment": comment
        }).execute()

    return {"message": "Review salva"}

@app.get("/me/profile")
async def my_profile(user=Depends(get_supabase_user)):
    row = supabase_admin.table("profiles").select("*").eq("user_id", str(user.id)).execute()
    if row.data:
        return row.data[0]
    default_username = (user.email.split("@")[0] if user.email else f"user_{str(user.id)[:6]}")
    ins = supabase_admin.table("profiles").insert({
        "user_id": str(user.id),
        "username": default_username
    }).execute()
    return ins.data[0]

@app.post("/me/profile/username")
async def change_username(request: Request, user=Depends(get_supabase_user)):
    body = await request.json()
    new_username = sanitize_text(body.get("username", ""), 30)
    if not new_username:
        raise HTTPException(status_code=400, detail="Username inválido")

    row = supabase_admin.table("profiles").select("*").eq("user_id", str(user.id)).execute()
    if not row.data:
        profile = supabase_admin.table("profiles").insert({
            "user_id": str(user.id),
            "username": new_username
        }).execute().data[0]
        return profile

    profile = row.data[0]
    last_changed = profile.get("username_changed_at")
    if last_changed:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(last_changed.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta_days = (now - dt).days
        if delta_days < 7:
            raise HTTPException(status_code=400, detail=f"Você só pode mudar o username após 7 dias. Faltam {7-delta_days} dia(s).")

    up = supabase_admin.table("profiles").update({
        "username": new_username,
        "username_changed_at": datetime.utcnow().isoformat()
    }).eq("user_id", str(user.id)).execute()
    return up.data[0]
"""

    write(BACKEND, text)

def patch_frontend():
    # React CDN single-file frontend
    html = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Config Heaven</title>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    body{margin:0;background:#070b12;color:#e8eef8;font-family:Inter,system-ui}
    .wrap{max-width:1100px;margin:0 auto;padding:24px}
    .title{font-size:42px;font-weight:900}
    .sub{opacity:.85;margin-bottom:18px}
    .card{background:#101827;border:1px solid #1f2937;border-radius:14px;padding:14px;margin:10px 0}
    .row{display:flex;gap:10px;flex-wrap:wrap}
    .btn{background:#00e4b6;color:#04120f;border:0;padding:8px 12px;border-radius:10px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}
    .pill{padding:4px 10px;border-radius:999px;background:#0b1320;border:1px solid #1f2937}
    input,select,textarea{background:#0b1220;color:#dfe8f6;border:1px solid #273244;border-radius:8px;padding:8px;width:100%}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
    .srv img{width:34px;height:34px;border-radius:999px}
    .muted{opacity:.75;font-size:13px}
  </style>
</head>
<body>
  <div id="app"></div>

  <script type="text/babel">
    const API = '/api';

    const SERVERS = [
      {name:'hylex.gg', detector:'grim', img:'https://static-cdn.jtvnw.net/jtv_user_pictures/8cc858dd-345b-46fe-b59d-355bd1463141-profile_image-300x300.png'},
      {name:'Kaizen', detector:'grim', img:'https://yt3.googleusercontent.com/8GrA2kC2lG-DXJJI6SHrcELQHZN3IfD_2UbQUd4SJX3GYrVyOFs1nncCNV0roZFBL9pLrlnMBGk=s160-c-k-c0x00ffffff-no-rj'},
      {name:'Mush', detector:'Mush-Prediction', img:'https://static-cdn.jtvnw.net/jtv_user_pictures/8cc858dd-345b-46fe-b59d-355bd1463141-profile_image-300x300.png'}
    ];

    const DOWNLOADS = {
      Legit: [
        ['Slinky','https://www.mediafire.com/file/1o209cxbzkpz58i/slinkyload.zip/file'],
        ['Doomsday','https://doomsdayclient.com/'],
        ['Haru','https://www.mediafire.com/file/palkwq3pcdak4ql/Haru-2.38.jar/file'],
        ['Elixe','https://github.com/ponei/elixe/releases/tag/7'],
      ],
      Blatant: [
        ['Astolfo','https://www.mediafire.com/file/18xq7e4wij0ox4j/Astolfo-LATEST.zip/file'],
        ['Augustus (cc)','https://www.mediafire.com/file/n43lmn7p7c8as4b/Augustus.zip/file'],
        ['Myau','https://www.mediafire.com/file/h7usx9o2s98wd4z/MYAU.jar/file'],
        ['Myau+','https://github.com/IamNespola/OpenMyau-Plus/releases'],
        ['Avocado','https://www.mediafire.com/file/qc76zztrq689c6m/avocado-b1.5.jar/file'],
        ['VestigeR','https://www.mediafire.com/file/ieny7lgmzc7hglq/VestigeR+1.1.0-1.zip/file'],
        ['LiquidBounce','https://github.com/CCBlueX/LiquidLauncher/releases/download/v0.5.0/LiquidLauncher_0.5.0_x64_en-US.msi'],
        ['Sigma 5.0','https://www.mediafire.com/file/kn8lcf562gduhtl/Sigma5.rar/file'],
        ['Sigma 4.11','https://www.mediafire.com/file/7ahv0sgq87zhfba/Sigma.zip/file'],
        ['RavenB-','https://www.mediafire.com/file/kvgasv2le25rv73/RavenB-Cracked.jar/file'],
        ['Biggie','https://www.mediafire.com/file/twfnzshqn2fppkm/Biggie.rar/file'],
      ],
      HvH: [
        ['Exhibition','https://www.mediafire.com/file/wifn28ba26mt68d/2024.rar/file'],
        ['libraries.rar','https://www.mediafire.com/file/71wra3nk7ma8zab/libraries.rar/file']
      ]
    };

    const CLIENT_OPTIONS = [
      'slinky','doomsday','haru','elixe',
      'astolfo','augustus','myau','myau+','avocado','vestigereborn','liquidbounce','sigma5','sigma4.11','ravenb-','biggie',
      'exhibition'
    ];

    async function api(method, path, body){
      const st = localStorage.getItem('mc_s');
      const token = st ? JSON.parse(st).t : null;
      const headers = {'Content-Type':'application/json'};
      if(token) headers['Authorization'] = 'Bearer ' + token;
      const r = await fetch(API + path, {method, headers, body: body ? JSON.stringify(body) : undefined});
      const d = await r.json().catch(()=>({}));
      if(!r.ok) throw new Error(d.detail || 'Erro');
      return d;
    }

    function App(){
      const [configs,setConfigs] = React.useState([]);
      const [q,setQ] = React.useState('');
      const [client,setClient] = React.useState('all');
      const [type,setType] = React.useState('all');

      const load = async ()=>{
        let url = '/configs?';
        if(type!=='all') url += `type=${encodeURIComponent(type)}&`;
        if(client!=='all') url += `client=${encodeURIComponent(client)}&`;
        if(q) url += `search=${encodeURIComponent(q)}&`;
        const d = await api('GET',url);
        setConfigs(d.configs||[]);
      };

      React.useEffect(()=>{ load().catch(()=>{}); },[]);

      const copyJvm = async ()=>{
        const txt='-XX:+DisableAttachMechanism -Xss4m';
        await navigator.clipboard.writeText(txt);
        alert('Argumentos JVM copiados: ' + txt);
      };

      return (
        <div className="wrap">
          <div className="title">Config Heaven</div>
          <div className="sub">A Newgen of Blatant, Legit and Ghost configs</div>

          <div className="card">
            <div className="row srv">
              {SERVERS.map(s=>(
                <div key={s.name} className="pill row" style={{alignItems:'center'}}>
                  <img src={s.img} alt={s.name}/>
                  <div><b>{s.name}</b><div className="muted">{s.detector}</div></div>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="row">
              <input placeholder="buscar..." value={q} onChange={e=>setQ(e.target.value)} />
              <select value={client} onChange={e=>setClient(e.target.value)}>
                <option value="all">Todos clients</option>
                {CLIENT_OPTIONS.map(c=><option key={c} value={c}>{c}</option>)}
              </select>
              <select value={type} onChange={e=>setType(e.target.value)}>
                <option value="all">Todos tipos</option>
                <option value="legit">legit</option>
                <option value="blatant">blatant</option>
                <option value="ghost">ghost</option>
              </select>
              <button className="btn" onClick={load}>Filtrar</button>
            </div>
          </div>

          <div className="grid">
            {configs.map(c=>(
              <div className="card" key={c.id}>
                <b>{c.name || 'sem nome'}</b>
                <div className="muted">{c.author} · {c.client} · {c.type}</div>
                <div className="muted">{c.server || 'sem servidor'} · views: {c.views || 0}</div>
                <div className="row" style={{marginTop:8}}>
                  <a className="btn" href={c.file_url} target="_blank">Download</a>
                </div>
              </div>
            ))}
          </div>

          <div className="card">
            <h3>Downloads por categoria</h3>
            {Object.entries(DOWNLOADS).map(([cat,list])=>(
              <div key={cat} style={{marginBottom:12}}>
                <b>{cat}</b>
                <div className="row" style={{marginTop:8}}>
                  {list.map(([name,url])=>(
                    <a className="btn" key={name} href={url} target="_blank">{name}</a>
                  ))}
                </div>
              </div>
            ))}
            <div className="card">
              <b>Exhibition - aviso</b>
              <div className="muted">Use os argumentos JVM:</div>
              <button className="btn" onClick={copyJvm}>Copiar argumentos JVM</button>
              <div className="muted" style={{marginTop:6}}>
                Também extraia o <b>libraries.rar</b> dentro da pasta <b>.minecraft</b>.
              </div>
            </div>
          </div>
        </div>
      );
    }

    ReactDOM.createRoot(document.getElementById('app')).render(<App />);
  </script>
</body>
</html>
"""
    write(FRONT, html)

def main():
    patch_sql()
    patch_backend()
    patch_frontend()
    print("✅ apply_fix_all concluído.")
    print(f"SQL migration criada em: {MIG}")

if __name__ == "__main__":
    main()