# systemd deployment

1. Copy the project to `/opt/hh_agent`.
2. Create `.env` in `/opt/hh_agent`.
3. Create a dedicated Linux user:
   `sudo useradd --system --create-home --home-dir /opt/hh_agent --shell /usr/sbin/nologin hhagent`
4. Review `hh-agent.service` and adjust `User`, `Group`, `WorkingDirectory`, and `ExecStart` if needed.
5. Install the unit:
   `sudo cp deploy/systemd/hh-agent.service /etc/systemd/system/hh-agent.service`
6. Reload and start:
   `sudo systemctl daemon-reload`
   `sudo systemctl enable --now hh-agent`
7. Check logs:
   `sudo journalctl -u hh-agent -f`
