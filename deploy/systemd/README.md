# systemd 运行单元

本目录保存 Ubuntu 部署脚本使用的 systemd 模板，不作为首选人工安装入口。

- `solution-workspace-backend.service.in`：以独立后端账号运行、仅监听回环地址的 FastAPI 服务。
- `solution-workspace-frontend.service.in`：以无密钥访问权的独立前端账号运行 Vinext 和同源 API 代理。
- `solution-workspace-backup.service.in`：使用 SQLite Online Backup API 生成并校验备份。
- `solution-workspace-backup.timer`：每天自动触发一次本机备份。
- `solution-workspace.target`：统一启停前后端。
- `install.sh`：由 Ubuntu 一键部署和运维更新流程调用的底层安装器。

新服务器请从仓库根目录执行：

```bash
sudo bash deploy/ubuntu/install.sh --public-host 服务器IP或域名
```

完整的部署、配置、数据库切换、备份恢复和故障处理步骤见
[Ubuntu 部署与运维手册](../../docs/UBUNTU_DEPLOYMENT.md)。
