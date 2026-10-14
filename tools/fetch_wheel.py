"""
从 PyTorch 官方索引下载 wheel,并绕开慢速 CDN 节点。

背景(2026-10-14 实测):
    https://download.pytorch.org/whl/cu130/torch/ 页面里的下载链接全部指向
    download-r2.pytorch.org,该节点本机实测只有 0.08~0.14 MB/s;
    而同一路径换到 download.pytorch.org 则有 2.2~2.4 MB/s —— 相差约 28 倍。
    1.8 GB 的 torch wheel 走慢节点要约 6.5 小时,走快节点约 14 分钟。

本脚本做的事:
    1. 拉取索引页,解析出匹配的 wheel 文件名与真实大小;
    2. 把 CDN 主机名改写成快的那个;
    3. 带 Range 断点续传下载到工作区内,可反复重跑;
    4. 校验大小,完成后打印本地路径。

用法:
    .python\\python.exe tools\\fetch_wheel.py --list
    .python\\python.exe tools\\fetch_wheel.py torch
    .python\\python.exe tools\\fetch_wheel.py torch --version 2.10.0

退出码非 0 即失败。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

INDEX_URL = "https://download.pytorch.org/whl/cu130"
# 索引页给的是这个主机,但它在本机很慢;同名路径换到下面这个主机就快得多。
SLOW_HOST = "download-r2.pytorch.org"
FAST_HOST = "download.pytorch.org"

_WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEST = os.path.join(_WS, ".tmp", "wheels")

_UA = {"User-Agent": "pip/26.1.1"}


def _open(url: str, headers: dict | None = None, timeout: int = 60):
    h = dict(_UA)
    if headers:
        h.update(headers)
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout)


def list_wheels(package: str) -> list[tuple[str, str]]:
    """返回 [(文件名, 下载 URL)],只保留本机能装的 cp312 / win_amd64。

    索引页里同一个 wheel 可能出现多次(实测页面确实有重复 href),
    这里按文件名去重并保持首次出现的顺序。
    """
    url = f"{INDEX_URL}/{package}/"
    html = _open(url).read().decode("utf-8", "replace")
    hrefs = re.findall(r'href="([^"]+\.whl)(?:#[^"]*)?"', html)
    seen: set[str] = set()
    out = []
    for h in hrefs:
        name = urllib.parse.unquote(h.rsplit("/", 1)[-1])
        if "cp312" not in name or "win_amd64" not in name:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append((name, h))
    return out


def parse_version(filename: str) -> str:
    # torch-2.10.0+cu130-cp312-cp312-win_amd64.whl -> 2.10.0
    m = re.match(r"^[^-]+-(.+?)(?:\+[^-]+)?-cp\d+", filename)
    return m.group(1) if m else ""


def pick(wheels: list[tuple[str, str]], version: str | None) -> tuple[str, str]:
    if not wheels:
        raise SystemExit("no matching wheel found")
    if version:
        for name, url in wheels:
            if parse_version(name) == version:
                return name, url
        raise SystemExit(f"version {version} not found; available: "
                         + ", ".join(sorted({parse_version(n) for n, _ in wheels})))
    # 默认取版本号最大的
    def key(item):
        return [int(x) for x in re.findall(r"\d+", parse_version(item[0]))]
    return max(wheels, key=key)


def rewrite(url: str) -> str:
    return url.replace(SLOW_HOST, FAST_HOST)


def remote_size(url: str) -> int:
    r = _open(url, {"Range": "bytes=0-0"})
    cr = r.headers.get("Content-Range", "")
    m = re.search(r"/(\d+)$", cr)
    if m:
        return int(m.group(1))
    return int(r.headers.get("Content-Length", 0))


def download(url: str, dest: str, total: int, chunk: int = 1 << 20) -> None:
    have = os.path.getsize(dest) if os.path.exists(dest) else 0
    if have >= total:
        print(f"  already complete: {have/2**20:.1f} MB")
        return

    mode = "ab" if have else "wb"
    headers = {"Range": f"bytes={have}-"} if have else {}
    if have:
        print(f"  resuming at {have/2**20:.1f} / {total/2**20:.1f} MB")

    t0 = time.time()
    done = have
    last = t0
    with _open(url, headers, timeout=120) as r, open(dest, mode) as f:
        while True:
            b = r.read(chunk)
            if not b:
                break
            f.write(b)
            done += len(b)
            now = time.time()
            if now - last >= 15:
                sp = (done - have) / 2**20 / max(now - t0, 0.01)
                pct = 100 * done / total
                eta = (total - done) / 2**20 / max(sp, 0.01) / 60
                print(f"  {pct:5.1f}%  {done/2**20:7.1f}/{total/2**20:.1f} MB"
                      f"  {sp:5.2f} MB/s  eta {eta:4.0f} min", flush=True)
                last = now

    final = os.path.getsize(dest)
    if final != total:
        raise SystemExit(f"size mismatch: got {final}, expected {total}")
    print(f"  done: {final/2**20:.1f} MB in {(time.time()-t0)/60:.1f} min")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Download PyTorch wheels from the fast CDN node.")
    ap.add_argument("package", nargs="?", default="torch")
    ap.add_argument("--version", default=None)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args(argv)

    wheels = list_wheels(args.package)
    if args.list:
        for name, _ in sorted(wheels, key=lambda x: parse_version(x[0])):
            print(name)
        return 0

    name, url = pick(wheels, args.version)
    url = rewrite(url)
    os.makedirs(_DEST, exist_ok=True)
    dest = os.path.join(_DEST, name)

    print(f"package : {args.package}")
    print(f"wheel   : {name}")
    print(f"host    : {url.split('/')[2]}  (rewritten from {SLOW_HOST})")
    print(f"dest    : {dest}")

    total = remote_size(url)
    print(f"size    : {total/2**20:.1f} MB")
    download(url, dest, total)
    print()
    print(f"LOCAL WHEEL: {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
