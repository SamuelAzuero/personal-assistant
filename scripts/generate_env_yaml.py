#!/usr/bin/env python3
import os

env_file = '.env'
out_file = 'deploy/cloud_run_env.yaml'

with open(env_file, 'r', encoding='utf-8') as f:
    lines = f.readlines()

yaml_lines = []
for line in lines:
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    if '=' in line:
        k, v = line.split('=', 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k == 'PORT':
            continue
        if k == 'DATABASE_PATH':
            v = '/app/data/assistant.db'
        elif k == 'APP_ENV':
            v = 'production'
        elif k == 'MOCK_SERVICES':
            v = 'false'
        elif k == 'TELEGRAM_SECRET_TOKEN' and not v:
            v = 'production_webhook_secret_token'
        yaml_lines.append(f'{k}: "{v}"')

os.makedirs('deploy', exist_ok=True)
with open(out_file, 'w', encoding='utf-8') as f:
    for yl in yaml_lines:
        f.write(yl + '\n')

print(f'Generated {out_file} with {len(yaml_lines)} variables.')
