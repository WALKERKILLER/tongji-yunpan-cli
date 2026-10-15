# Disclaimer

This project is an unofficial, community-maintained command-line tool for
Tongji Yunpan (AnyShare).

It is not affiliated with, endorsed by, or supported by Tongji University,
AISHU, AnyShare, or any related organization. All product names and trademarks
belong to their respective owners.

## Use at your own risk

- Use this tool only with your own account, or with an account that you have
  explicit permission to use.
- Do not use this tool to access, modify, or share files without authorization.
- Follow the terms of service of Tongji Yunpan, your school's policies, and all
  applicable laws and regulations.
- The tool may stop working when the server-side API, login flow, or permission
  model changes.

## Credentials and data

- You are responsible for the account, password, token, and configuration files
  used with this tool.
- The CLI stores the OAuth2 token in `~/.config/tongjiyunpan/token.json`. If you
  use `--store-password`, the password is stored as plain text in
  `~/.config/tongjiyunpan/config.json`.
- Do not commit configuration or token files to a Git repository.
- A share link can expose a file to anyone who has the link. Treat share links
  as public data unless you are sure the audience is limited.

## No warranty

This software is provided "as is", without warranty of any kind. The authors and
contributors are not liable for data loss, data disclosure, account restriction,
service interruption, or any other damage caused by using this software.

## Third-party notices

The login flow, endpoint selection, and RSA public key were developed with
reference to the AnyShare REST API documentation and the MIT-licensed
[Pansh](https://github.com/Fucov/Pansh) project. Pansh is an independent
project and is not affiliated with this project.
