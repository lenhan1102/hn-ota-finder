module.exports = {
  apps: [
    {
      name: "ota-finder",
      script: "run.py",
      interpreter: ".venv/bin/python3",
      cwd: __dirname,
      env: {
        PORT: 8090,
        HOST: "0.0.0.0",
        PYTHONUNBUFFERED: "1",
        RELOAD: "false",
        APP_ENV: "production",
        HOME: "/home/tide",
        PLAYWRIGHT_BROWSERS_PATH: "/home/tide/.cache/ms-playwright",
      },
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "2G",
      error_file: "logs/err.log",
      out_file: "logs/out.log",
      merge_logs: true,
      time: true,
    },
  ],
};
