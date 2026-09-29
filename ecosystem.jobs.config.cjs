const fs = require('fs');
const path = require('path');

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

// Measured throughput is ~30s per company, so a full 546-company sweep takes
// roughly 4.5h. Running every batch sequentially inside one short-lived cron
// job keeps that wall time in a single process, outside the APScheduler thread
// pool the funding-event jobs depend on.
const BATCH_SIZE = 25;
const TOTAL_BATCHES = 22;

const batchArgs = [];
for (let i = 0; i < TOTAL_BATCHES; i++) {
  batchArgs.push(i * BATCH_SIZE, BATCH_SIZE);
}

module.exports = {
  apps: [
    {
      name: 'fund-job-radar-jobs-sweep',
      script: '.venv/bin/python',
      args: `-m app.job_worker ${batchArgs.join(' ')}`,
      cwd: '/mnt/e/Code/fund-job-radar',
      interpreter: 'none',
      autorestart: false,
      watch: false,
      env: {
        PYTHONPATH: '/mnt/e/Code/fund-job-radar',
        ...env
      },
      cron_restart: '0 3 * * *'
    }
  ]
};
