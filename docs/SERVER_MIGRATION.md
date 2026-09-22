# 生产服务器迁移手册

适用：Ubuntu + systemd、单节点 SQLite。先在隔离的新服务器演练，再切换访问入口。
迁机与产品升级分开进行：新服务器先运行旧服务器的确切提交，确认数据与功能后再升级。

## 1. 迁机前记录

在旧服务器保存以下结果；旧更新器没有 doctor 时，分别执行 status、health、db-info 和备份 timer 检查：

~~~bash
sudo solution-workspace doctor
sudo git -C /opt/solution-workspace rev-parse HEAD
sudo solution-workspace db-info
sudo solution-workspace backup
~~~

需要转移的内容：

- 一致性数据库备份及同名 .manifest.json，文件名保持一致。
- /etc/solution-workspace/app.env，必须保留原 MVP_LLM_CONFIG_SECRET，否则数据库中保存的大模型凭据无法解密。
- 确切代码提交、所需依赖或可访问的软件源，以及定制的反向代理、HTTPS、域名和防火墙配置。
- deploy.conf 作为参考记录；新服务器使用安装器重新生成，不直接覆盖新环境的部署路径。

配置文件走受控渠道，保持限制权限；不要把密钥或正式数据库提交到 Git。
不要直接复制正在写入的 SQLite 主文件，在线备份会处理 WAL 中的数据。

## 2. 隔离演练

1. 新服务器先不向业务用户开放。在干净的源码仓库中，将 main 定位到旧服务器记录的提交，或检出对应发布标签。
2. 用 Ubuntu 安装脚本准备依赖、服务账号和运行目录。此时可以使用默认试用库，不能让用户写入。
3. 停止新服务器的应用和备份 timer/service。备份新生成的 app.env，再复制旧服务器的配置。
4. 核对新服务器的访问域名/IP、服务端口、数据库路径与 Cookie/HTTPS 配置；保持原加密密钥。
5. 将数据库和清单以原名放入数据目录根层，设置后端账号可读权限，执行校验和切换：

~~~bash
# 用实际的备份文件名替换下方示例；两个文件必须来自同一次备份
sudo solution-workspace verify-db /var/lib/solution-workspace/mvp-时间戳.db
sudo solution-workspace switch-db /var/lib/solution-workspace/mvp-时间戳.db
sudo solution-workspace doctor
~~~

切换前 app.env 的 MVP_DATABASE_URL 应仍指向新服务器已创建的试用库；由 switch-db 负责切换目标。
否则会提示“目标数据库已在使用”，也无法为试用库生成切换前快照。

验证账号登录、权限、项目/任务/工作记录/周报数量，以及 AI 配置能否读取与连接。
只通过健康接口不能证明业务数据正确。确认新服务器的备份能生成、校验并复制到异机位置。

## 3. 正式切换

1. 通知维护窗口，关闭旧服务器的业务访问入口。
2. 停止旧服务器应用和自动备份任务，确认后端、前端都处于 inactive，再生成最后一次备份：

~~~bash
sudo solution-workspace stop
sudo systemctl stop solution-workspace-backup.timer solution-workspace-backup.service
sudo systemctl is-active solution-workspace-backend.service solution-workspace-frontend.service
sudo solution-workspace backup
~~~

is-active 在服务停止时返回非零是预期结果；必须查看输出并确认两者均已停止。
最终快照生成后，旧服务器保持停写，不能恢复业务访问。

3. 停止新服务器写入，将最终备份和清单按第 2 节校验并切换；重复业务对账及 doctor 检查。
4. 验证新服务器访问入口后再切换域名、反向代理或访问地址。
5. 保留旧服务器、最终快照、原配置与提交记录，直到回滚窗口结束。

## 4. 回退边界

如果新服务器还没有业务写入，可停止新服务器、恢复旧服务器应用和备份 timer，再恢复旧入口。
如果新服务器已经产生写入，不能直接把入口切回旧库，否则会丢失新增数据；先冻结双方写入并进行数据对账及反向迁移。

数据库切换、升级、独立迁移失败时，以命令打印的“当前状态”为准。
如果提示恢复未完成，先检查服务状态和日志，不要重复安装或重新生成密钥。
断电、强制杀进程无法执行清理回调，需要检查 /var/backups/solution-workspace 中的专用回滚目录。

## 5. 新服务器仍需验证的项目

仓库内故障测试使用模拟服务和隔离数据库；它不能替代真实主机验收。
在新服务器实测 systemd 权限、依赖源、磁盘容量、正式数据库备份耗时、代理/HTTPS、自动备份及一次恢复演练。
代码 bundle 不含 Node.js、Python、npm 和系统软件依赖；完全断网迁机需另行准备匹配 CPU 架构和版本的依赖制品。
