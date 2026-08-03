# -*- coding: utf-8 -*-
"""
东京 H5 站点（hehuan.qzz.io）只读客户端
=======================================
[AI-2026-08-02]

用途：本机主程序的「东京后台维护」面板 + 命令行诊断脚本共用同一份取数逻辑，
      避免两处实现漂移。**只读**，不含任何写/推送能力（推送走 deploy/H5web/）。

为什么不是一句 urlopen 就完事——两个实测踩过的坑：

1) IPv6 黑洞
   hehuan.qzz.io 挂在 Cloudflare，DNS 同时返回 IPv6(2606:4700:...) 与
   IPv4(104.21.x / 172.67.x)。本机 IPv6 连出去不回 RST、直接吞包。
   curl 有 Happy Eyeballs，秒回退 IPv4（实测 1.9s 拿到 200）；
   Python urllib 没有回退，会死等到 timeout 耗尽。
   → 解法：自定义 HTTPSConnection 只解析 AF_INET。
     刻意**不**全局 monkeypatch socket.getaddrinfo——主程序同时还有
     IB / 富途 / 腾讯行情在用 socket，全局改会殃及池鱼。

2) Cloudflare 拦截默认 UA
   Python 默认 UA (python-urllib/3.x) 会被直接回 403。
   → 解法：带常规浏览器 UA（实测 curl UA / Chrome UA 均放行）。
"""
import http.client as _httpclient
import json
import os
import socket as _socket
import time
import urllib.request as _urlreq
from datetime import datetime

# 允许用环境变量覆盖（比如临时指到别的站点做对比）
TOKYO_BASE = os.environ.get("ARB_TOKYO_BASE", "https://hehuan.qzz.io").rstrip("/")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class _IPv4HTTPSConnection(_httpclient.HTTPSConnection):
    """强制 IPv4 的 HTTPS 连接（原因见模块 docstring 第 1 条）。"""

    def connect(self):
        infos = _socket.getaddrinfo(
            self.host, self.port, _socket.AF_INET, _socket.SOCK_STREAM)
        if not infos:
            raise OSError(f"{self.host} 无可用 IPv4 地址")
        self.sock = _socket.create_connection(
            infos[0][4], self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()
        server_hostname = self._tunnel_host or self.host
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=server_hostname)


class _IPv4HTTPSHandler(_urlreq.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req, context=self._context)


# build_opener 保留其余默认 handler，只把 HTTPSHandler 换成强制 IPv4 的版本
_opener = _urlreq.build_opener(_IPv4HTTPSHandler())


def fetch_tokyo_json(name: str, timeout: int = 20):
    """读取东京公网 JSON（如 'fund_data.json' / 'fund_rt.json'）。

    带时间戳查询串 + no-cache 头，避免 Cloudflare 边缘缓存返回旧数据骗人。
    失败直接抛异常，由调用方决定怎么展示。
    """
    url = f"{TOKYO_BASE}/{name}?_t={int(time.time())}"
    req = _urlreq.Request(url, headers={
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": _UA,
        "Accept": "application/json,text/plain,*/*",
    })
    with _opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def age_minutes(ts):
    """'YYYY-mm-dd HH:MM:SS' -> 距今分钟数；解析失败返回 None。"""
    if not ts:
        return None
    try:
        gen = datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
        return round((datetime.now() - gen).total_seconds() / 60.0, 1)
    except Exception:
        return None
