module.exports = {
  apps: [{
    name: 'fund-job-radar',
    script: '.venv/bin/python',
    args: '-m app.main',
    cwd: '/mnt/e/Code/fund-job-radar',
    interpreter: 'none',
    autorestart: true,
    watch: false,
    max_memory_restart: '500M',
    env: {
      PYTHONPATH: '/mnt/e/Code/fund-job-radar'
    }
  }]
};
