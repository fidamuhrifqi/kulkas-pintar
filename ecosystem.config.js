module.exports = {
  apps: [
    {
      name: "kulkas-bot",
      script: "bot.py",
      // Gunakan "./venv/Scripts/python" untuk Windows
      // Gunakan "./venv/bin/python3" untuk Linux/Mac
      interpreter: "./venv/bin/python3",
      env: {
        NODE_ENV: "production",
      },
      // Restart policy
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      // Logging
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "./logs/error.log",
      out_file: "./logs/out.log",
      merge_logs: true,
      // Watch (disabled for production)
      watch: false,
    },
  ],
};
