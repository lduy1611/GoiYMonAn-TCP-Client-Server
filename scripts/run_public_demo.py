"""Run the demo against an explicitly provisioned unified-v3 MySQL database."""
from __future__ import annotations
import argparse, hashlib, json, os, secrets, shutil, socket, sys, threading, time
from pathlib import Path
from urllib.request import urlopen
from dotenv import dotenv_values
import mysql.connector
import uvicorn
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def port_available(host: str, port: int) -> bool:
    with socket.socket() as sock:
        try: sock.bind((host,port)); return True
        except OSError: return False

def configure(env_file=None) -> dict[str,str]:
    config={k:str(v) for k,v in dotenv_values(env_file or ROOT/".env",interpolate=False).items() if v is not None}
    config.update({k:v for k,v in os.environ.items() if k.startswith(("UNIFIED_","TCP_","WEB_","ADMIN_","USER_","GOIY_DEMO_"))})
    required=("UNIFIED_MYSQL_HOST","UNIFIED_MYSQL_PORT","UNIFIED_MYSQL_USER","UNIFIED_MYSQL_PASSWORD","UNIFIED_MYSQL_DATABASE")
    missing=[k for k in required if not config.get(k)]
    if missing: raise RuntimeError("Config is incomplete; use .env.demo.example with your own local MySQL settings")
    if any(config.get(k,"").lower().startswith(("replace", "change_me")) for k in ("ADMIN_PASSWORD","UNIFIED_MYSQL_PASSWORD")):
        raise RuntimeError("Replace local password placeholders in .env before starting")
    if config["UNIFIED_MYSQL_HOST"] not in {"127.0.0.1","localhost","::1"} or not config["UNIFIED_MYSQL_DATABASE"].endswith("_test"):
        raise RuntimeError("Public demo requires a loopback MySQL database ending in _test")
    if bool(config.get("ADMIN_USERNAME")) != bool(config.get("ADMIN_PASSWORD")):
        raise RuntimeError("Provide both optional Admin fields, or neither")
    if config.get("ADMIN_PASSWORD"):
        salt=secrets.token_bytes(16)
        digest=hashlib.pbkdf2_hmac("sha256",config["ADMIN_PASSWORD"].encode("utf-8"),salt,600_000,dklen=32)
        config["ADMIN_PASSWORD_HASH"]=f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"
    if len(config.get("ADMIN_SESSION_SECRET", "")) < 32 or config.get("ADMIN_SESSION_SECRET", "").startswith("REPLACE"):
        config["ADMIN_SESSION_SECRET"]=secrets.token_urlsafe(48)
    runtime_root=Path(config.get("GOIY_DEMO_RUNTIME_DIR", ROOT/"statics/runtime/public-demo"))
    config.update({
      "TCP_DB_SCHEMA":"unified_v3","UNIFIED_SCHEMA_MODE":"1",
      "TCP_HOST":config.get("TCP_HOST","127.0.0.1"),"TCP_PORT":config.get("TCP_PORT","9000"),
      "TCP_MAX_CONNECTIONS":config.get("TCP_MAX_CONNECTIONS","4"),
      "UNIFIED_TCP_DB_POOL_SIZE":config.get("UNIFIED_TCP_DB_POOL_SIZE","4"),
      "WEB_HOST":config.get("WEB_HOST","127.0.0.1"),"WEB_PORT":config.get("WEB_PORT","8000"),
      "ADMIN_COOKIE_SECURE":"false","USER_COOKIE_SECURE":"false",
      "RECIPE_IMAGE_STORAGE_DIR":str(runtime_root/"recipe-images"),
      "ACHIEVEMENT_IMAGE_STORAGE_DIR":str(runtime_root/"achievement-images"),
      "FEEDBACK_IMAGE_STORAGE_DIR":str(runtime_root/"feedback-images"),
      "TCP_LOG_PATH":str(runtime_root/"tcp.jsonl"),
      "FASTAPI_GATEWAY_LOG_PATH":str(runtime_root/"fastapi.jsonl"),
      "MEAL_PLAN_STATE_DIR":str(runtime_root/"meal-state"),
    })
    for key in ("WEB_PORT", "TCP_PORT", "UNIFIED_MYSQL_PORT"):
        if not 1 <= int(config[key]) <= 65535:
            raise RuntimeError("Invalid demo port")
    if config["TCP_HOST"] not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("TCP must remain bound to IPv4 loopback")
    if int(config["TCP_PORT"]) == int(config["WEB_PORT"]):
        raise RuntimeError("TCP and web ports must differ")
    return config

def prepare_images(env):
    """Verify the public package and copy missing images; never overwrite uploads."""
    base=ROOT/"data/demo"
    manifest=json.loads((base/"manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256((base/"catalog.sql").read_bytes()).hexdigest()!=manifest["catalog_sha256"]:
        raise RuntimeError("Public catalog checksum mismatch")
    destination=Path(env["RECIPE_IMAGE_STORAGE_DIR"])
    for item in manifest["images"]:
        source=base/item["path"]
        if not source.resolve().is_relative_to(base.resolve()):
            raise RuntimeError("Invalid public image path")
        if hashlib.sha256(source.read_bytes()).hexdigest()!=item["sha256"]:
            raise RuntimeError("Public image checksum mismatch")
    destination.mkdir(parents=True,exist_ok=True)
    for item in manifest["images"]:
        target=destination/Path(item["path"]).name
        if not target.exists():
            # Exclusive creation protects pre-existing runtime images.
            with target.open("xb") as stream, (base/item["path"]).open("rb") as source:
                shutil.copyfileobj(source,stream)
    return manifest

def verify_database(env:dict[str,str])->dict[str,int|str]:
    conn=mysql.connector.connect(host=env["UNIFIED_MYSQL_HOST"],port=int(env["UNIFIED_MYSQL_PORT"]),user=env["UNIFIED_MYSQL_USER"],password=env["UNIFIED_MYSQL_PASSWORD"],database=env["UNIFIED_MYSQL_DATABASE"],charset="utf8mb4",connection_timeout=5)
    try:
      cur=conn.cursor(dictionary=True)
      cur.execute("SELECT COUNT(*) AS total,SUM(is_public=1 AND deleted_at IS NULL) AS public FROM recipes")
      recipes=cur.fetchone()
      cur.execute("SELECT COUNT(*) AS total FROM ingredients")
      ingredients=cur.fetchone()["total"]
      cur.execute("SELECT COUNT(*) AS total FROM achievement_posts")
      achievements=cur.fetchone()["total"]
      return {"database":env["UNIFIED_MYSQL_DATABASE"],"recipes_total":int(recipes["total"]),"recipes_public":int(recipes["public"] or 0),"ingredients":int(ingredients),"achievement_posts":int(achievements)}
    finally: conn.close()

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file",type=Path,help="Separate local config; never modified")
    args=parser.parse_args()
    env=configure(args.env_file)
    web_host=env["WEB_HOST"]; web_port=int(env["WEB_PORT"]); tcp_port=int(env["TCP_PORT"])
    if not port_available("127.0.0.1",tcp_port) or not port_available(web_host if web_host!="0.0.0.0" else "0.0.0.0",web_port):
      raise RuntimeError("A configured demo port is busy; no other process was stopped")
    data=verify_database(env)
    prepare_images(env)
    os.environ.update(env)
    from source.server.main import TCPServer,configured_tcp_max_connections
    from source.server.unified_repository import UnifiedMySQLRepository
    from source.web.main import app
    tcp=TCPServer("127.0.0.1",tcp_port,max_connections=configured_tcp_max_connections(),repository=UnifiedMySQLRepository.from_env())
    tcp_thread=threading.Thread(target=tcp.serve_forever,name="demo-tcp",daemon=True); tcp_thread.start()
    api_server=None; api_thread=None
    try:
      for _ in range(100):
        if not tcp_thread.is_alive(): raise RuntimeError("TCP Server stopped during startup")
        try:
          with socket.create_connection(("127.0.0.1",tcp_port),timeout=.15): break
        except OSError: time.sleep(.05)
      else: raise RuntimeError("TCP Server did not become ready")
      api_server=uvicorn.Server(uvicorn.Config(app,host=web_host,port=web_port,log_level="info",access_log=False))
      api_thread=threading.Thread(target=api_server.run,name="demo-fastapi",daemon=True); api_thread.start()
      for _ in range(100):
        if not api_thread.is_alive() or not tcp_thread.is_alive(): raise RuntimeError("A demo service stopped during startup")
        try:
          with urlopen(f"http://127.0.0.1:{web_port}/api/health",timeout=1) as response:
            health=json.loads(response.read().decode("utf-8"))
            if response.status==200 and (health.get("data") or {}).get("dataset_version","").startswith("unified:"): break
        except Exception: time.sleep(.15)
      else: raise RuntimeError("FastAPI health did not confirm the unified database through TCP")
      print(json.dumps({"status":"ready","database":data,"mysql":f"{env['UNIFIED_MYSQL_HOST']}:{env['UNIFIED_MYSQL_PORT']}","tcp":"127.0.0.1:"+str(tcp_port),"web":"http://127.0.0.1:"+str(web_port),"admin":"http://127.0.0.1:"+str(web_port)+"/admin"},ensure_ascii=False),flush=True)
      while api_thread.is_alive() and tcp_thread.is_alive(): time.sleep(1)
      raise RuntimeError("A demo service exited unexpectedly")
    except KeyboardInterrupt:
      return 0
    finally:
      if api_server is not None: api_server.should_exit=True
      tcp.shutdown()
      if api_thread is not None: api_thread.join(timeout=8)
      tcp_thread.join(timeout=8)
if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc:
      print("Demo startup failed: "+type(exc).__name__+": "+str(exc),file=sys.stderr)
      raise SystemExit(1)
