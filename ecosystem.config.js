module.exports = {
  apps: [
    {
      name: "kulkas-bot",
      script: "bot.py",
      interpreter: "./venv/bin/python3",
      cwd: "/home/ubuntu/kulkas-pintar/kulkas-bot",
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
