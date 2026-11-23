"""Run addon integration tests in a new, disposable Odoo database; never use the user's database."""
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "olist-intelligence-odoo-1"


def main():
    keep = "--keep-database" in sys.argv
    suffix = uuid.uuid4().hex[:10]
    database = "olist_ai_test_" + suffix
    addon_path = "/tmp/olist-ai-addons-" + suffix
    subprocess.run(["docker", "exec", CONTAINER, "mkdir", "-p", addon_path], check=True)
    subprocess.run(["docker", "cp", str(ROOT / "odoo_addons/olist_sales_ai"), CONTAINER + ":" + addon_path + "/olist_sales_ai"], check=True)
    script = '''
import configparser, os, subprocess, tempfile
import psycopg2
from psycopg2 import sql
database = __DATABASE__
keep = __KEEP__
assert database.startswith('olist_ai_test_')
with tempfile.TemporaryDirectory(prefix='olist-ai-test-') as work:
    config = configparser.ConfigParser()
    config['options'] = {'db_host':os.environ['HOST'], 'db_user':os.environ['USER'], 'db_password':os.environ['PASSWORD'],
        'db_port':os.environ.get('PORT','5432'), 'addons_path':__ADDON_PATH__+',/usr/lib/python3/dist-packages/odoo/addons',
        'data_dir':'/var/lib/odoo' if keep else work+'/data', 'http_enable':'False', 'log_level':'test', 'limit_time_real':'0', 'workers':'0'}
    path=work+'/odoo.conf'
    with open(path,'w') as stream:config.write(stream)
    os.chmod(path,0o600)
    code=1
    try:
        result=subprocess.run(['odoo','-c',path,'-d',database,'-i','olist_sales_ai','--without-demo',
            '--http-port','8079','--stop-after-init','--test-enable','--test-tags','/olist_sales_ai'])
        code=result.returncode
    finally:
        conn=psycopg2.connect(host=os.environ['HOST'],user=os.environ['USER'],password=os.environ['PASSWORD'],dbname='postgres')
        conn.autocommit=True
        if not keep or code:
            with conn.cursor() as cursor:cursor.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(database)))
        conn.close()
    if keep and not code:print('QA_DATABASE='+database,flush=True)
    raise SystemExit(code)
'''.replace("__DATABASE__", repr(database)).replace("__ADDON_PATH__", repr(addon_path)).replace("__KEEP__", repr(keep))
    result = subprocess.run(["docker", "exec", "-i", CONTAINER, "python3", "-"], input=script, text=True)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
