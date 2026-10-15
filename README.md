# tongji-yunpan-cli

**English** | [简体中文](README.zh-CN.md)

Unofficial command-line client for Tongji Yunpan (AnyShare). It logs in with a
Tongji account, lists directories, uploads and downloads files, creates
long-term share links, and resolves those links into signed download URLs for
automation.

This project is not affiliated with Tongji University or AISHU. Read
[DISCLAIMER.md](DISCLAIMER.md) before use.

## Features

- Login with account and password, then store the OAuth2 token.
- Refresh the token automatically or log in again when a stored password exists.
- List document libraries and directories.
- Create remote directories.
- Upload a single file up to 5 GiB.
- Download files through signed URLs.
- Get short-lived signed download URLs.
- Create long-term anonymous share links.
- Resolve or download from a share link without logging in.
- Print JSON for automation.

## Requirements

- Python 3.10 or later
- `requests`
- `pycryptodome`
- Network access to `https://yunpan.tongji.edu.cn`

## Install

```bash
cd tongjiyunpan
pip install -e .
```

You can also run the repo-local launcher without installing:

```bash
./typan --help
```

## Login

Use environment variables to avoid shell history and config files:

```bash
export TY_USERNAME='your-student-id'
export TY_PASSWORD='your-password'
typan login
```

Run `typan login` without environment variables to enter the account and
password interactively.

By default the CLI stores only the OAuth2 token. To store the password as
plain text for unattended re-login:

```bash
typan login --store-password
```

Plain-text storage is risky. Prefer environment variables or a secret manager.

## Commands

| Command | Purpose |
|---|---|
| `login` | Log in and save the token. |
| `logout` | Remove the saved token. |
| `whoami` | Print the current user. |
| `ls [path]` | List top-level document libraries or the contents of a directory. |
| `mkdir <path>` | Create a remote directory. |
| `upload <local> <remote-dir>` | Upload a file. |
| `download <remote> [local]` | Download a file. |
| `url <remote>` | Get a short-lived signed download URL. |
| `share <remote>` | Create or reuse a long-term anonymous share link. |
| `share-url <share>` | Resolve a long-term share link to a signed URL. No login required. |
| `share-download <share> [local]` | Download from a long-term share link. No login required. |
| `config show` | Show the local config with the password masked. |

Add `--json` to most commands for machine-readable output.

## Remote paths

Use `~` for the personal document library root:

```bash
typan ls ~
typan upload ./report.pdf '~/reports'
typan download '~/reports/report.pdf' ./report.pdf
```

A full name path starts with a document library name:

```bash
typan ls 'Name(StudentID)/reports'
```

Names can contain Chinese characters, spaces, and parentheses. Quote the path
in the shell.

## Download URLs and share links

`typan url` returns a signed object-storage URL. The URL expires in about
15 minutes.

```bash
typan url '~/app_logo.png'
typan url '~/app_logo.png' --json
```

`typan share` creates a browser-facing long-term link in the form
`https://yunpan.tongji.edu.cn/link/<link_id>`. The default expiry is
`2099-12-31T23:59:59+08:00`, with no password and unlimited access.

```bash
typan share '~/app_logo.png'
typan share '~/app_logo.png' --json
typan share '~/app_logo.png' --new
```

Reuse an existing link for the same file unless `--new` is given.

A long-term share link opens a web page. For automation, resolve it to a fresh
signed URL or download directly:

```bash
typan share-url 'https://yunpan.tongji.edu.cn/link/xxxxxxxx'
typan share-download 'https://yunpan.tongji.edu.cn/link/xxxxxxxx' ./file.bin
```

Both commands need no account and no token.

## Configuration

Default config directory: `~/.config/tongjiyunpan/`

| Environment variable | Purpose |
|---|---|
| `TY_USERNAME` | Account used for login. |
| `TY_PASSWORD` | Password used for login. |
| `TY_BASE_URL` | Service URL. Default: `https://yunpan.tongji.edu.cn`. |
| `TY_CONFIG_DIR` | Override the config directory. |

Files:

- `config.json`: account, base URL, and optional plain-text password.
- `token.json`: OAuth2 access, refresh, and ID tokens. File mode is `0600`.

## Security

- Do not commit `config.json` or `token.json`.
- A share link exposes the file to anyone who has the link. Share only files
  that are safe to expose.
- Use environment variables or a secret manager in automated jobs.
- Restrict the permissions of the account that runs the CLI.

## Limitations

- Single-file upload is limited to about 5 GiB. Multipart upload is not
  implemented.
- Move, copy, and delete commands are not implemented.
- `share-url` and `share-download` support single-file share links. Folder
  shares need a browser.
- Share links with an access password are not supported by the CLI resolver.
- Login depends on the current Tongji Yunpan web login flow. A server-side
  change can break it.

## Acknowledgements

The login flow, endpoint selection, and RSA public key were developed with
reference to the AnyShare REST API documentation and the MIT-licensed
[Pansh](https://github.com/Fucov/Pansh) project.

## License

MIT. See [LICENSE](LICENSE).
