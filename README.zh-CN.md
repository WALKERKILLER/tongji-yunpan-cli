# tongji-yunpan-cli

[English](README.md) | **简体中文**

同济云盘（AnyShare）的非官方命令行工具。支持登录、列目录、上传、下载、创建长期分享链接，也支持把分享链接解析成带签名的下载直链。

本项目与同济大学、爱数（AISHU）无关。使用前请阅读 [DISCLAIMER.md](DISCLAIMER.md)。

## 功能

- 用账号和密码登录，保存 OAuth2 令牌。
- 令牌过期自动刷新。配置了密码时，自动重新登录。
- 列文档库和目录。
- 创建远端目录。
- 上传单文件，最大 5 GiB。
- 下载文件。
- 获取临时下载直链。
- 创建长期匿名分享链接。
- 不登录解析或下载分享链接。
- 输出 JSON，方便脚本调用。

## 环境要求

- Python 3.10 或更高版本
- `requests`
- `pycryptodome`
- 能访问 `https://yunpan.tongji.edu.cn`

## 安装

```bash
cd tongjiyunpan
pip install -e .
```

不安装也可以直接用仓库里的启动器：

```bash
./typan --help
```

## 登录

用环境变量传入账号和密码，避免写入命令历史和配置文件：

```bash
export TY_USERNAME='你的学号'
export TY_PASSWORD='你的密码'
typan login
```

不设置环境变量时，`typan login` 会提示输入账号和密码。

默认只保存令牌，不保存密码。无人值守需要自动重登时，可以执行：

```bash
typan login --store-password
```

明文保存密码有风险。自动化任务优先用环境变量或密钥管理服务。

## 常用命令

| 命令 | 作用 |
|---|---|
| `login` | 登录并保存令牌。 |
| `logout` | 删除本地令牌。 |
| `whoami` | 查看当前用户。 |
| `ls [path]` | 列顶层文档库，或列某个目录。 |
| `mkdir <path>` | 创建远端目录。 |
| `upload <local> <remote-dir>` | 上传文件。 |
| `download <remote> [local]` | 下载文件。 |
| `url <remote>` | 获取临时下载直链。 |
| `share <remote>` | 创建或复用长期匿名分享链接。 |
| `share-url <share>` | 把长期分享链接解析成临时直链，不需要登录。 |
| `share-download <share> [local]` | 从长期分享链接下载，不需要登录。 |
| `config show` | 查看本地配置，密码会打码。 |

大多数命令支持 `--json`。

## 远端路径

`~` 表示个人文档库根目录：

```bash
typan ls ~
typan upload ./report.pdf '~/reports'
typan download '~/reports/report.pdf' ./report.pdf
```

完整路径从文档库名称开始：

```bash
typan ls '姓名(学号)/reports'
```

路径可以包含中文、空格和括号。在 shell 里记得加引号。

## 下载直链和分享链接

`typan url` 返回对象存储的签名直链，大约 15 分钟后过期。

```bash
typan url '~/app_logo.png'
typan url '~/app_logo.png' --json
```

`typan share` 创建浏览器访问的长期链接，格式为
`https://yunpan.tongji.edu.cn/link/<link_id>`。默认有效期到
`2099-12-31T23:59:59+08:00`，无密码，不限访问次数。

```bash
typan share '~/app_logo.png'
typan share '~/app_logo.png' --json
typan share '~/app_logo.png' --new
```

同一个文件已有链接时，默认复用。加 `--new` 可以强制新建。

长期分享链接打开后是网页。自动化流程可以把它解析成新的临时直链，或直接下载：

```bash
typan share-url 'https://yunpan.tongji.edu.cn/link/xxxxxxxx'
typan share-download 'https://yunpan.tongji.edu.cn/link/xxxxxxxx' ./file.bin
```

这两个命令不需要登录，也不需要令牌。

## 配置

默认配置目录：`~/.config/tongjiyunpan/`

| 环境变量 | 作用 |
|---|---|
| `TY_USERNAME` | 登录账号。 |
| `TY_PASSWORD` | 登录密码。 |
| `TY_BASE_URL` | 服务地址，默认 `https://yunpan.tongji.edu.cn`。 |
| `TY_CONFIG_DIR` | 替换配置目录。 |

文件：

- `config.json`：账号、服务地址，以及可选的明文密码。
- `token.json`：OAuth2 的 access、refresh 和 ID 令牌，权限为 `0600`。

## 安全建议

- 不要把 `config.json` 和 `token.json` 提交到仓库。
- 分享链接会暴露文件。只分享可以公开的文件。
- 自动化任务用环境变量或密钥管理服务传密码。
- 限制运行 CLI 的账号权限。

## 限制

- 单文件上传上限约 5 GiB，暂不支持分片上传。
- 暂不支持移动、复制和删除命令。
- `share-url` 和 `share-download` 只支持单文件分享。目录分享需要在浏览器里打开。
- 带访问密码的分享链接暂不支持解析。
- 登录流程依赖当前的同济云盘网页登录方式。服务端更新后可能失效。

## 致谢

登录流程、接口选择和 RSA 公钥的实现参考了 AnyShare REST API 文档，以及 MIT 协议的 [Pansh](https://github.com/Fucov/Pansh) 项目。

## 许可证

MIT，见 [LICENSE](LICENSE)。
