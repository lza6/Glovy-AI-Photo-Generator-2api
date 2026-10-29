# Glovy 2API → new-api 对接指南（可照做版）

> 你（对接方）只需要：① 启动本网关 ② 在 new-api 建一个渠道 ③ 按下面清单验证。
> 网关已把上游 Apero 协议全部封装，**new-api 侧不需要写任何 adaptor**。

---

## 1. 拓扑

```
用户 → new-api(渠道: OpenAI 类型) → http://<host>:8956 (本网关) → api-img-gen-wrapper.aperogroup.ai
```

网关对 new-api 暴露的是**标准 OpenAI 形状**：

- `GET  /v1/models`
- `POST /v1/images/generations`（文生图）
- `POST /v1/images/edits`（图生图 / 风格化 / 11 种图像处理）

视频走网关原生 `POST /api/v1/video`（OpenAI 没有对应标准端点，见 §5）。

---

## 2. 启动网关

```powershell
cd D:\apk-analysis\glovy\2api
pip install fastapi uvicorn requests cryptography

# 2.1 配 key（三选一，优先级从高到低）
$env:APERO_API_KEY = "sk-..."                       # A. 环境变量
# B. 复制 config.example.json → config.json，填 api_key
# C. python fetch_rc.py --app fravix                 # 从 Firebase Remote Config 现取

# 2.2 配代理（国内网络必须，否则上游连接不稳）
$env:APERO_PROXY = "http://127.0.0.1:10808"

# 2.3 起服务
$env:PORT = "8956"
python server.py
```

自检三条：

```powershell
curl http://127.0.0.1:8956/health        # {"ok":true,"mock":false,"styles":3826,...}
curl http://127.0.0.1:8956/v1/models     # 15 个模型（3 基础 + 11 处理 + 视频）
curl http://127.0.0.1:8956/api/v1/operations   # 11 项能力清单与必填输入
```

`APERO_MOCK=1` 可离线跑通全链路（不消耗上游），适合先联调 new-api。

---

## 3. new-api 渠道配置（字段级）

| new-api 字段 | 填什么 |
|---|---|
| 渠道类型 | **OpenAI**（`type = 1`） |
| 渠道名称 | `Glovy-2API` |
| 代理 / Base URL | `http://127.0.0.1:8956`（new-api 与网关不同机则填内网 IP） |
| 密钥 | 任意非空串，如 `sk-local-glovey`（**网关不校验入站 key**，靠内网隔离） |
| 模型 | 见 §4 列表（至少填 `glovy/text2image`、`glovy/image-edit`） |
| 分组 / 倍率 | 按你的策略 |

> 若 new-api 的图像渠道要求填「绘图模型」，把 §4 里 `glovy/*` 全填进去即可；
> 未列出的模型 new-api 侧会直接 404，不会打到上游。

---

## 4. 模型 ↔ 能力 映射（**对接核心**）

### 4.1 文生图 — `/v1/images/generations`

| 模型名 | 行为 |
|---|---|
| `glovy/text2image` | Flux-Klein 文生图，`size` 支持 256~1536（如 `768x768`/`1024x1024`），`n` 1~4 |
| `glovy/enhance` … | **不要用这个端点**（这些是图生图能力，需传图） |

可选参数：`style_id`（style-manager 的 24 位 ObjectId）、`seed`。
`style_id` 见网关 `/styles` 或 `styles_v3.json`（3826 条）。

### 4.2 图生图 / 图像处理 — `/v1/images/edits`

网关按 **`model` 名** 路由到不同上游能力（也可显式传 form 字段 `op=`）：

| 模型名 | 上游能力 | 必填 |
|---|---|---|
| `glovy/image-edit` 或 `glovy/flux-klein-editing` | 风格化 / 通用图生图 | `image`、`prompt`；可选 `style_id` |
| `glovy/enhance` | 画质增强 | `image` |
| `glovy/restore` | 老照片修复 | `image` |
| `glovy/outpaint` | 扩图（`prompt` 描述扩展内容） | `image`、`prompt` |
| `glovy/remove-bg` | 抠背景 | `image` |
| `glovy/qwen-edit` | 自然语言编辑 | `image`、`prompt` |
| `glovy/beauty` | 人像美颜 | `image` |
| `glovy/clothes` | AI 换装 | `image`、`prompt` |
| `glovy/segment` | 图像分割 | `image` |
| `glovy/remove-object` | 去物体 | `image` + `mask` |
| `glovy/inpainting` | 局部重绘 | `image` + `mask` + `prompt` |
| `glovy/fitting` | 服装试穿（双图） | 建议直接用网关原生端点（需 `cloth` 图） |

> multipart 字段：`image`(file, 必填)、`prompt`(text)、`mask`(file, 可选)、`style_id`(text, 可选)、`op`(text, 可选)。
> 网关返回 `{"created":..,"data":[{"url":"https://static.aperogroup.ai/..."}]}`。

### 4.3 视频 — 网关原生

| 接口 | 说明 |
|---|---|
| `POST /api/v1/video` | multipart：`image`(file)、`prompt`(动作描述)、`mode`(默认 `i2v`)、`timeout_s`(默认 300) |
| 返回 | `{"type":"video","status":"completed","url":"...mp4","elapsed_ms":~35000}` |
| 产出规格 | h264 / 704×704 / 121 帧 / ~5 s / ~900 KB，端到端 ~35 s |

new-api 若用「任务/MJ 类渠道」接视频，需要写薄适配（OpenAI 无标准视频端点）；**如果只要图片，跳过本节。**

---

## 5. 验证（照序执行，每步都要绿）

```powershell
# ① 网关直连 — 文生图
curl -X POST http://127.0.0.1:8956/v1/images/generations ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"a cozy cabin in snowy forest\",\"model\":\"glovy/text2image\",\"size\":\"768x768\"}"

# ② 网关直连 — 图生图（带风格）
curl -X POST http://127.0.0.1:8956/v1/images/edits ^
  -F "image=@D:\apk-analysis\fravix\in1.jpg" ^
  -F "prompt=studio portrait, soft light" ^
  -F "model=glovy/image-edit" ^
  -F "style_id=64b260c21d50d66f545ea9f8"

# ③ 网关直连 — 图像处理能力（增强）
curl -X POST http://127.0.0.1:8956/v1/images/edits ^
  -F "image=@D:\apk-analysis\fravix\in1.jpg" ^
  -F "prompt=enhance" ^
  -F "model=glovy/enhance"

# ④ 网关直连 — 视频（可选）
curl -X POST http://127.0.0.1:8956/api/v1/video ^
  -F "image=@D:\apk-analysis\fravix\in1.jpg" ^
  -F "prompt=the girl smiles gently, hair moves in the wind"

# ⑤ 经 new-api（把 base/key/模型换成你的）
curl -X POST http://<new-api>/v1/images/generations ^
  -H "Authorization: Bearer sk-<你的令牌>" ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"a cyberpunk cat\",\"model\":\"glovy/text2image\",\"size\":\"768x768\"}"
```

全部应返回 `data[0].url = https://static.aperogroup.ai/...jpeg`（视频为 `.mp4`）。

---

## 6. 定价、限流、超时

| 项 | 建议值 | 依据 |
|---|---|---|
| 渠道超时 | **≥ 180 s**（视频 ≥ 360 s） | 实测 i2i p95 14.3 s，长尾 30 s+；视频 ~35 s |
| 渠道并发 | **≤ 4** | 上游 `/health` 显示 `wrapper.limit = 20`，超过易排队失败 |
| 每分钟请求 | ≤ 20/min | 同上 |
| 重试 | 1 次 | 网关内置 1 次重试，new-api 再叠加 1 次足够 |
| 文生图计价倍率 | 1.0× | 实测 p50 6.4 s |
| 图生图 / 处理 | 1.2× | 实测 p50 8.0 s，enhance/restore 更慢 |
| 视频 | 单列高价或暂不上架 | ~35 s/条，成本最高 |

**不要给免费额度**：上游额度是别人的客户端凭据，被打爆会被厂商封 key。

---

## 7. 排错表

| 现象 | 原因 | 处理 |
|---|---|---|
| 502 `HTTP 412 Precondition Failed` | 时钟偏差过大 / 代理不通 | 重启网关（启动会同步上游时间）；确认 `APERO_PROXY` |
| 502 `HTTP 401 Not active api key` | 当前 key 被上游停用 | 换 key：`APERO_API_KEY` 或 `python fetch_rc.py --app fravix` |
| 502 `HTTP 404 Not found api key` | key 空/占位 | 同上；确认 `config.json` 已填 |
| 502 `The provided style ID does not exist` | `style_id` 用了数字 id | 用 `/styles` 的 24 位 ObjectId |
| 502 `client.bad-request` | 视频缺 `notificationProvider/notificationId`（网关已自动补）；op 缺 mask | 见 §4 |
| 400 `unknown op` / 404 模型不存在 | 模型名不在 §4 表内 | 用 `/v1/models` 校对 |
| 出图 200 但前端打不开 | 直连 `static.aperogroup.ai` 失败 | 走网关 `/media?url=...` 代理 |
| 视频 status=failed | 极少见上游排队失败 | 重试一次；仍失败降频 |

---

## 8. 已知限制（务必知悉）

1. **key 依附性**：Glovy 自身 key 已被上游标记 `Not active`，现用同厂在运营 App（Fravix/AIP862）的 key。
   厂商随时可停 → 保留 `fetch_rc.py` 一键换 key 能力，必要时做 key 池。
2. **合规风险**：这是第三方在运营服务的客户端凭据，非自建额度。转发他人 App 的 key 有被封风险，
   **不要大规模并发、不要对外免费开放**。
3. **segment** 返回 201 但 `data:[]`（还需档位参数），暂不建议上架。
4. **fitting** 需双图，建议走网关原生 `/api/v1/op/fitting`（multipart 加 `cloth` 文件）。
5. 上游结果 CDN 域名 `static.aperogroup.ai`，(部分网络直连失败) → 用 `/media` 代理。

---

## 9. 交接清单

- [ ] 网关跑在固定端口，`/health` 返回 `ok:true`
- [ ] `APERO_PROXY` 已配置且在 new-api 所在网络可用
- [ ] new-api 渠道（OpenAI 类型）建好，Base URL 指向网关
- [ ] 模型列表已填 `glovy/*`（§4）
- [ ] §5 的 ①②③⑤（+④可选）四步全绿
- [ ] 渠道超时 ≥180s、并发 ≤4、重试 1
- [ ] 计价倍率已设，未开放免费额度
- [ ] 已知限制（§8）已同步给运营
