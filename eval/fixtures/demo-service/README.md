# demo-service

评估用例 `demo-inspect-service` 的最小 fixture 项目。
试跑器会把整个目录复制到 `eval/.runtime/<batch>/workspaces/<case>/trial_N/target`，
并注册为名为 `eval-<case>-t<N>-<suffix>` 的临时 Target。

- `README.md`：服务自述，供只读巡检用例读取。
- `logs/app.log`：存在此文件时试跑器会自动把它配成 target 的 `log_path`。
- `config/app.conf`：演示配置文件读取。
