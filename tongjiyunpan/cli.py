"""Command-line interface for Tongji Yunpan."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .client import DEFAULT_BASE_URL, YunpanClient, YunpanError

CONFIG_ENV = "TY_CONFIG_DIR"
USERNAME_ENV = "TY_USERNAME"
PASSWORD_ENV = "TY_PASSWORD"
BASE_URL_ENV = "TY_BASE_URL"


def _config_dir() -> Path:
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "tongjiyunpan"


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_json(path: Path, data: Any, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if private:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
        size /= 1024
    return f"{size:.1f}T"


def _load_config():
    return _load_json(_config_dir() / "config.json", {})


def _load_token():
    return _load_json(_config_dir() / "token.json", {})


def _client(args: argparse.Namespace) -> YunpanClient:
    config = _load_config()
    token = _load_token()
    base_url = args.base_url or os.environ.get(BASE_URL_ENV) or config.get("base_url") or DEFAULT_BASE_URL
    username = args.username or os.environ.get(USERNAME_ENV) or config.get("username")
    password = args.password or os.environ.get(PASSWORD_ENV) or config.get("password")
    client = YunpanClient(
        base_url=base_url,
        token=token or None,
        username=username,
        password=password,
    )
    client.on_token_updated = lambda: _save_token(client)
    if token:
        return client
    if username and password:
        client.login()
        _save_token(client)
        return client
    raise YunpanError(
        "尚未登录。请运行 `typan login`，或设置 TY_USERNAME/TY_PASSWORD（或 TONGJI_YUNPAN_USERNAME/TONGJI_YUNPAN_PASSWORD）。"
    )


def _save_token(client: YunpanClient) -> None:
    _save_json(_config_dir() / "token.json", client.token, private=True)


def _print_entry(item: dict[str, Any], is_dir: bool) -> str:
    kind = "d" if is_dir else "f"
    return f"{kind}  {_human_size(int(item.get('size', 0))):>10}  {item.get('name', '')}"


def cmd_login(args: argparse.Namespace) -> int:
    config = _load_config()
    username = args.username or os.environ.get(USERNAME_ENV) or config.get("username")
    if not username:
        username = input("账号: ").strip()
    password = args.password or os.environ.get(PASSWORD_ENV) or config.get("password")
    if not password:
        password = getpass.getpass("密码: ")
    base_url = args.base_url or os.environ.get(BASE_URL_ENV) or config.get("base_url") or DEFAULT_BASE_URL
    client = YunpanClient(base_url=base_url)
    try:
        client.login(username, password)
    except YunpanError as exc:
        print(f"登录失败: {exc}", file=sys.stderr)
        return 1
    _save_token(client)
    config = dict(config)
    config["username"] = username
    config["base_url"] = base_url
    if args.store_password:
        config["password"] = password
    _save_json(_config_dir() / "config.json", config, private=True)
    print(f"登录成功: {username}")
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    token_path = _config_dir() / "token.json"
    if token_path.exists():
        token_path.unlink()
    print("已清除本地登录令牌")
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        info = client.whoami()
    except YunpanError as exc:
        print(f"获取用户信息失败: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"账号: {info.get('account')}")
        print(f"姓名: {info.get('name')}")
        print(f"用户ID: {info.get('userid')}")
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        if not args.path or args.path in ("", "."):
            # No path => show all top-level document libraries.
            libs = client.list_doc_libs()
            if args.json:
                print(json.dumps(libs, ensure_ascii=False, indent=2))
            else:
                for lib in libs:
                    print(f"{lib.get('type','')}  {lib.get('name','')}  {lib.get('id','')}")
            return 0
        info = client.resolve_path(args.path)
        if info.get("size", 0) != -1:
            # A single file.
            if args.json:
                print(json.dumps({**info, "type": "file"}, ensure_ascii=False, indent=2))
            else:
                print(_print_entry(info, False))
            return 0
        dirs, files = client.list_dir(info["docid"])
        if args.json:
            data = {
                "path": args.path,
                "dirs": dirs,
                "files": files,
            }
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            for d in dirs:
                print(_print_entry(d, True))
            for f in files:
                print(_print_entry(f, False))
    except YunpanError as exc:
        print(f"列目录失败: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_mkdir(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        path = args.path.strip().strip("/")
        if path == "~":
            raise YunpanError("不能直接在个人文档库根目录上创建同名目录，请提供目录名")
        parts = [p for p in path.split("/") if p]
        if not parts:
            raise YunpanError("目录名为空")
        name = parts[-1]
        parent = "/".join(parts[:-1]) if len(parts) > 1 else "~"
        parent_info = client.resolve_path(parent)
        result = client.create_dir(parent_info["docid"], name, ondup=args.ondup)
        docid = result.get("docid") or result.get("id", "")
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"已创建目录: {args.path}  ({docid})")
    except YunpanError as exc:
        print(f"创建目录失败: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        result = client.upload_file(
            args.local,
            args.remote_dir,
            name=args.name,
            ondup=args.ondup,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"上传成功: {result.get('name')} -> {args.remote_dir}")
            print(f"  docid: {result.get('docid')}")
            print(f"  size:  {result.get('size')}")
    except YunpanError as exc:
        print(f"上传失败: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        local = client.download_file(
            args.remote,
            local_path=args.local,
            force=args.force,
            filename=args.filename,
        )
        if args.json:
            print(json.dumps({"local": str(local)}, ensure_ascii=False, indent=2))
        else:
            print(f"下载完成: {local}")
    except YunpanError as exc:
        print(f"下载失败: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_url(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        info = client.get_download_info(args.remote, filename=args.filename)
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            print(info["url"])
    except YunpanError as exc:
        print(f"获取直链失败: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_share(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        if args.list:
            links = client.list_share_links(args.remote)
            if args.json:
                print(json.dumps(links, ensure_ascii=False, indent=2))
            else:
                for link in links:
                    print(
                        f"{link.get('id', '')}  {link.get('expires_at', '')}  "
                        f"{link.get('title', '')}"
                    )
            return 0
        allow: list[str] = []
        if not args.no_display:
            allow.append("display")
        if not args.no_preview:
            allow.append("preview")
        if not args.no_download:
            allow.append("download")
        if not allow:
            allow = ["display"]
        result = client.create_share_link(
            args.remote,
            title=args.title,
            expires_at=args.expires_at,
            password=args.password or "",
            limited_times=args.limited_times,
            allow=allow,
            reuse_existing=not args.new,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(result["url"])
            if result.get("password"):
                print(f"密码: {result['password']}")
            print(f"有效期至: {result.get('expires_at')}")
    except YunpanError as exc:
        print(f"创建分享链接失败: {exc}", file=sys.stderr)
        return 1
    return 0


def _anonymous_client(args: argparse.Namespace) -> YunpanClient:
    config = _load_config()
    base_url = args.base_url or os.environ.get(BASE_URL_ENV) or config.get("base_url") or DEFAULT_BASE_URL
    return YunpanClient(base_url=base_url)


def cmd_share_url(args: argparse.Namespace) -> int:
    client = _anonymous_client(args)
    try:
        info = client.resolve_share_link(args.share, filename=args.filename)
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            print(info["url"])
    except YunpanError as exc:
        print(f"解析分享链接失败: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_share_download(args: argparse.Namespace) -> int:
    client = _anonymous_client(args)
    try:
        local = client.download_share_link(
            args.share,
            local_path=args.local,
            filename=args.filename,
            force=args.force,
        )
        if args.json:
            print(json.dumps({"local": str(local)}, ensure_ascii=False, indent=2))
        else:
            print(f"下载完成: {local}")
    except YunpanError as exc:
        print(f"从分享链接下载失败: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    config = _load_config()
    if args.action == "show":
        safe = {k: ("***" if "password" in k.lower() else v) for k, v in config.items()}
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        return 0
    if args.action == "set":
        config[args.key] = args.value
        _save_json(_config_dir() / "config.json", config, private=True)
        print(f"已设置 {args.key}")
        return 0
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="typan", description="同济云盘 (AnyShare) 命令行工具")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--base-url", default=None, help="云盘地址，默认 https://yunpan.tongji.edu.cn")
    parser.add_argument("--username", default=None, help="账号，也可用 TY_USERNAME 环境变量")
    parser.add_argument("--password", default=None, help="密码，也可用 TY_PASSWORD 环境变量")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="登录并保存令牌")
    p.add_argument("--username", dest="sub_username", default=None)
    p.add_argument("--password", dest="sub_password", default=None)
    p.add_argument("--store-password", action="store_true", help="把密码明文写入配置文件（谨慎）")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("logout", help="清除本地令牌")
    p.set_defaults(func=cmd_logout)

    p = sub.add_parser("whoami", help="查看当前用户")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_whoami)

    p = sub.add_parser("ls", help="列出文档库或目录")
    p.add_argument("path", nargs="?", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("mkdir", help="创建远端目录")
    p.add_argument("path")
    p.add_argument("--ondup", type=int, default=2, choices=[1, 2, 3], help="1报错 2自动重名 3覆盖")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_mkdir)

    p = sub.add_parser("upload", help="上传本地文件到云盘")
    p.add_argument("local")
    p.add_argument("remote_dir", help="目标远端目录，可用 ~ 表示个人文档库")
    p.add_argument("--name", default=None, help="远端文件名")
    p.add_argument("--ondup", type=int, default=2, choices=[1, 2, 3], help="1报错 2自动重名 3覆盖")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_upload)

    p = sub.add_parser("download", help="下载云盘文件")
    p.add_argument("remote")
    p.add_argument("local", nargs="?", default=None)
    p.add_argument("--filename", default=None, help="直链中的下载文件名")
    p.add_argument("--force", action="store_true", help="覆盖已存在的本地文件")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("url", help="获取临时文件下载直链")
    p.add_argument("remote")
    p.add_argument("--filename", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_url)

    p = sub.add_parser("share", help="创建/查看长期有效的匿名分享链接")
    p.add_argument("remote")
    p.add_argument("--title", default=None, help="分享标题")
    p.add_argument(
        "--expires-at",
        default="2099-12-31T23:59:59+08:00",
        help="过期时间，ISO8601；默认 2099-12-31",
    )
    p.add_argument("--password", default="", help="访问密码，留空表示无密码")
    p.add_argument("--limited-times", type=int, default=-1, help="-1 表示不限访问次数")
    p.add_argument("--no-display", action="store_true", help="不显示在分享页面")
    p.add_argument("--no-preview", action="store_true", help="不允许预览")
    p.add_argument("--no-download", action="store_true", help="不允许下载")
    p.add_argument("--new", action="store_true", help="已有链接时不复用，强制新建")
    p.add_argument("--list", action="store_true", help="仅列出已有分享链接")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_share)

    p = sub.add_parser("share-url", help="把长期分享链接解析为临时下载直链（无需登录）")
    p.add_argument("share", help="分享链接或 link id")
    p.add_argument("--filename", default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_share_url)

    p = sub.add_parser("share-download", help="从长期分享链接下载文件（无需登录）")
    p.add_argument("share", help="分享链接或 link id")
    p.add_argument("local", nargs="?", default=None)
    p.add_argument("--filename", default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_share_download)

    p = sub.add_parser("config", help="查看/设置配置")
    p.add_argument("action", choices=["show", "set"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Normalize global credentials to subcommand options where the subparser has
    # its own aliases.
    if hasattr(args, "sub_username") and args.sub_username:
        args.username = args.sub_username
    if hasattr(args, "sub_password") and args.sub_password:
        args.password = args.sub_password
    try:
        return args.func(args)
    except YunpanError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
