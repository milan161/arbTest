// [AI-2026-08-25] 启动顺序治理：先等后端健康再启 vite，从源头杜绝冷启动 race。
// 背景：早先后端 lifespan 初始化约 90 秒会阻塞 uvicorn 接请求，vite proxy 触发 ECONNREFUSED
// 返回纯文本 'Backend not ready'，前端 SSE parser 解析报 1300+ console 错误。
// 现已将静态估值/快照首刷改为后台 task，lifespan 秒级返回；本探针只等 uvicorn 真正 listen。
// 探针：/api/system/milestones 是纯内存 list，uvicorn listen 后即响应，零业务开销。
// 超时默认 30s（uvicorn 就绪为秒级；30s 仅为真卡死兜底，可用 WAIT_BACKEND_TIMEOUT_MS 覆盖）。
import { setTimeout as sleep } from 'node:timers/promises';

const BACKEND_URL = process.env.WAIT_BACKEND_URL || 'http://127.0.0.1:8000/api/system/milestones';
const TIMEOUT_MS = Number(process.env.WAIT_BACKEND_TIMEOUT_MS || 30_000);
const POLL_MS = 500;

async function probe() {
  try {
    const res = await fetch(BACKEND_URL, { signal: AbortSignal.timeout(2000) });
    return res.ok; // 200 = 后端 uvicorn 已 listen 且业务路由可用
  } catch {
    return false; // ECONNREFUSED / 超时 / 后端未起
  }
}

const start = Date.now();
let lastReportAt = start;
process.stdout.write(`[wait-backend] 等待后端就绪: ${BACKEND_URL} (最长 ${Math.round(TIMEOUT_MS / 1000)}s)\n`);
while (Date.now() - start < TIMEOUT_MS) {
  if (await probe()) {
    const secs = ((Date.now() - start) / 1000).toFixed(1);
    process.stdout.write(`[wait-backend] 后端已就绪 (${secs}s)，启动 vite...\n`);
    process.exit(0);
  }
  // 每 5 秒打印一次进度，避免终端看起来像卡死
  const elapsed = Date.now() - start;
  if (Date.now() - lastReportAt >= 5_000) {
    process.stdout.write(`[wait-backend] 已等待 ${(elapsed / 1000).toFixed(0)}s，后端仍在初始化...\n`);
    lastReportAt = Date.now();
  }
  await sleep(POLL_MS);
}
process.stderr.write(
  `[wait-backend] 超时(${Math.round(TIMEOUT_MS / 1000)}s)后端仍未就绪。\n` +
  `  请检查后端窗口(runback.bat)是否有报错，或手动 curl ${BACKEND_URL}\n`
);
process.exit(1); // && 链路中断，vite 不启动
