import sys
sys.path.insert(0, '.')

with open('agent/config.py', 'rb') as f:
    content = f.read()

print(f'文件大小: {len(content)} bytes')
print(f'前300字节:')
print(repr(content[:300]))
print()

print('尝试直接 exec:')
exec_globals = {}
try:
    exec(compile(content, 'config.py', 'exec'), exec_globals)
    print('exec 成功')
    vars_list = [k for k in exec_globals.keys() if not k.startswith('_')]
    print(f'定义的变量: {vars_list}')
    print(f'MAX_RETRIES = {exec_globals.get("MAX_RETRIES")}')
    print(f'DURABLE_CRON_PATH = {exec_globals.get("DURABLE_CRON_PATH")}')
except Exception as e:
    print(f'exec 失败: {e}')
    import traceback
    traceback.print_exc()
