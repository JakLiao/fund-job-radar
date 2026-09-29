const fs = require('fs');
const path = require('path');

// 从 .env 读取注入 PM2，避免 webhook 明文进入 ecosystem.config.cjs
const envPath = path.join(__dirname, '.env');
const env = {};
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const idx = trimmed.indexOf('=');
    if (idx === -1) continue;
    env[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim();
  }
}

module.exports = {
  apps: [
    {
      name: 'fund-job-radar',
      script: '.venv/bin/python',
      args: '-m app.main',
      cwd: '/mnt/e/Code/fund-job-radar',
      interpreter: 'none',
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      max_instances: 1,
      env: {
        PYTHONPATH: '/mnt/e/Code/fund-job-radar',
        ...env
      }
    }
  ]
};
