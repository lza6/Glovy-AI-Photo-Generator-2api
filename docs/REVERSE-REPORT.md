# Glovy – AI Photo Generator 1.9.0 逆向 / 2API 报告（第一轮）

- **目标 APK**：`Glovy---AI-Photo-Generator-V1.9.0-_modyolo.apk`（38.5 MB，Modyolo 重签名）
- **包名**：`com.aiphotogenerator.aivideomaker.photoslideshow`
- **业务 SDK**：`com.apero.aigenerate` / `com.apero.integrity` / `com.apero.signature`（Apero 集团 VisionLab 白标模板）
- **上游厂商**：Apero Group（越南），同类产品共用同一网关（Fravix / Kreivo / Glovy 等 54 个 project 共用风格库）
- **分析时间**：2026-10-29
- **状态**：图片链路（图生图 / 风格化 / 文生图）**全链路已打通并实测出图**；图生视频**创建+轮询已打通**

---

## 1. 域名与端点全表

| 服务 | 域名 | 用途 |
|---|---|---|
| 图片网关 | `https://api-img-gen-wrapper.aperogroup.ai` | 图生图 / 文生图 / 上传签名 |
| 视频网关 | `https://video-gen-core.aperogroup.ai` | 图生视频（异步） |
| 风格库 | `https://api-style-manager.aperogroup.ai` | 3826 条风格 + 590 类目 |
| 美颜 / 身体 | `https://beauty-core.aperogroup.ai` | FaceBeauty / BodyBeautify |
| 增强 | `https://enhance-core.aperogroup.ai` | image-enhance |
| 扩图 / 抠图 | `https://core-outpaint.aperogroup.ai` | outpaint / remove-bg |
| 修复 | `https://image-restore-core.aperogroup.ai` | restore |
| 分割 | `https://segment-core.aperogroup.ai` | segmentation |
| 换装 | `https://cloth-change-core.aperogroup.ai` | clothes / fitting |
| 去物体 | `https://objectremoval-core.aperogroup.ai` | remove-object |
| 高级绘图 | `https://art-premium-core.aperogroup.ai` | premium text-2-image |
| 结果 CDN | `https://static.aperogroup.ai` | 产出图直链 |
| 上传 | `s3.ap-southeast-1.amazonaws.com/cdn-prod-static-aperovn` | presigned PUT |

### 端点

| 方法 | 路径 | 说明 | 实测 |
|---|---|---|---|
| GET | `/timestamp` | 服务器时间（ms） | ✅ 200 |
| GET | `/health` | `{"isHealth":true,"details":[{"wrapper":{"limit":20}}]}` | ✅ 200 |
| GET | `/api/v5/image-ai/presigned-link` | 图生图上传直链 `{url,path}` | ✅ 200 |
| PUT | `{url}`（S3） | 上传原始图，**不带签名头** | ✅ 200 |
| POST | `/api/v5/image-ai` | 图生图 / 风格化（同步返回） | ✅ 201 |
| POST | `/api/v5/premium/text-2-image` | 文生图（同步返回） | ✅ 201 |
| GET | `/api/v5/image-2-video/presigned-link` | 视频上传直链（video-gen-core） | ✅ 200 |
| POST | `/api/v5/image-2-video` | 创建视频任务 | ✅ 201 |
| GET | `/api/v5/image-2-video/video/{videoId}` | 轮询 `videoStatus` | ✅ 200 |
| GET | `/api/v5.1/qwen-editing/presigned-link` + `POST /api/v5.1/qwen-editing` | Qwen 图像编辑（换装/合并） | 静态确认 |
| GET | `style-manager /v3/styles?page=N` | 风格库分页（100/页，39 页 = 3826 条） | ✅ 200 |
| GET | `style-manager /category` | 590 个类目（含 styles 子项） | ✅ 200 |
| 已废弃 | `/api/v4/image-ai` | 返回 `410 Deprecated, use v5 instead` | ✅ 410 |

其它静态端点（未逐个实测）：`/api/v5/image-enhance`、`/api/v5/image-outpainting`、`/api/v5/image-restore`、`/api/v1/image-inpainting`、`/api/v5/image-2-video`（video）。

---

## 2. 鉴权：RSA 信封签名（无 HMAC、无 pinning、无 Play Integrity 强制）

来源：`com/apero/signature/SignatureParserImpl.java` + `com/apero/aigenerate/network/interceptor/SignatureInterceptor.java`

```
signature = Base64( RSA_ECB_PKCS1v1_5( publicKey, f"{timestamp}@@@{api_key}@@@{rand(0..33554431)}" ) )
```

请求头（**每一个都必需**，缺任何一个 → 边缘层 412）：

| 头 | 值 | 备注 |
|---|---|---|
| `x-api-signature` | 上述签名 | RSA 公钥硬编码在 APK `BuildConfig.PUBLIC_KEY` 与 Firebase RC `app_public_key` |
| `x-api-timestamp` | 毫秒时间戳 | 与签名内一致；服务端有窗口校验（本机时钟偏差 1.4s 时仍通过） |
| `x-api-keyid` | api_key | `/timestamp` **不校验**，业务端点校验存在性 + 激活状态 |
| `x-api-token` | `not_get_api_token` | Play Integrity token 占位；实测**不校验**，无 Google 服务也可用 |
| `x-api-bundleId` | 包名 | 必需（缺 → 412）；实测**不与 key 绑定** |
| `App-name` | `AI_AIP862_...` 格式 | 必需 |
| `App-version` | `1.9.0` / `2.1.1` 均可 | 不严格 |
| `Country-code` | `US` / `VN` | 不校验 |
| `device` | `android` | 必需 |
| `User-Agent` | `okhttp/4.12.0` | 必需 |

**关键结论**：签名只覆盖「时间戳 + keyid + 随机数」，**不覆盖请求体**，因此一个合法签名可复用于任意请求（只需时间窗内刷新）；`x-api-token`（Play Integrity）与 bundleId 均非硬校验。

### 412 vs 401 vs 404 语义

| 状态 | errorCode | 含义 |
|---|---|---|
| 412 `Precondition Failed` | — | 头不齐（缺 UA/bundleId/签名），边缘层直接拒 |
| 404 `Not found api key` | ERR24 | keyid 在库中不存在 |
| 401 `Not active api key` | ERR15 | key 存在但被停用 |
| 400 `The provided style ID does not exist` | ERR16 | styleId 无效（会拼成 `style-manager/v3/styles/{id}` 去查） |
| 400 `client.bad-request` | ERR16 | 缺必填字段（视频：必须 `notificationProvider` + `notificationId`） |
| 410 | — | v4 已废弃 |

---

## 3. 凭据链：Firebase Remote Config

`ai_key` 来源（`p213e6/C13329i.java` case 7）：

```java
String apiKey = ((FirebaseRemoteConfig) this.f30969k).getString("api_key");
aiServiceConfig.setUpData(
    "AI_AIP893_AI_Photo_Video_Generator_Android",   // App-name
    "com.aiphotogenerator.aivideomaker.photoslideshow", // bundleId
    apiKey, application, false, "1.9.0", country, 60);
```

Firebase 凭据（`res/values/strings.xml` 明文）：

| 字段 | 值 |
|---|---|
| `google_api_key` | `AIzaSyDklS05WRgQYDwXSQSJHR9KPcWZutI8A-s` |
| `google_app_id` | `1:699734493584:android:aeb86c4cd39521de204b15` |
| `project_id` | `aip999-photo-video-slideshow` |
| `gcm_defaultSenderId` | `699734493584` |

拉取链（全部走 HTTPS REST，无需真机/无需 Play Integrity）：

```
1) POST firebaseinstallations.googleapis.com/v1/projects/{project}/installations
   headers: x-goog-api-key, X-Android-Package, X-Android-Cert(APK 签名 SHA1)
   → fid + authToken.token
   注: 实测用 mod 版签名（Modyolo SHA1 C8D25C…）也能通过

2) POST firebaseremoteconfig.googleapis.com/v1/projects/{project}/namespaces/firebase:fetch?key={google_api_key}
   headers: X-Goog-Firebase-Installations-Auth: {authToken}
   body: {app_id, app_instance_id: fid, package_name, country_code, language_code,
          platform_version, sdk_version, time_zone, app_version, app_build, first_open_time}
   → entries{} （Glovy 212 条，含 api_key）
   ⚠ body 里不要带 analytics_user_properties（会 400 Cannot bind a list to map）
```

### ⚠️ Glovy 自己的 key 已停用

- Glovy（AIP893）RC 下发的 `api_key` = `sk-1DkJe***` → 业务端点返回 **401 ERR15 `Not active api key`**
  （直连 / 德国代理 / VN country-code / 不同 App-name / 无 token 头 全部同样结果；IP 无关）
- 解法：Apero 网关的 key **不绑定 bundleId**，用同厂在运营 App 的 key 即可（本轮使用 Fravix 2.1.1 / AIP862 的 key，
  实测 200）。这同时说明：**key 是项目级租户标识，服务端不做 App 归属校验**。
- 兄弟 App 同样的 RC 结构（新版把凭据结构化下发）：
  `app_api_key` / `app_app_name` / `app_bundle_id` / `app_public_key`（公钥与 Glovy 完全一致）。

---

## 4. 业务协议细节

### 4.1 图生图 / 风格化（`POST /api/v5/image-ai`）

```json
{
  "file": "ai-core-flux-klein-editing/20261029/<uuid>/input.jpg",
  "styleId": "64b260c21d50d66f545ea9f8",      // 可选；来自 style-manager /v3/styles 的 _id
  "positivePrompt": "studio portrait, soft light",
  "negativePrompt": "...",
  "seed": 42,
  "imageSize": 1024,
  "fixWidth": 768, "fixHeight": 768, "fixWidthAndHeight": true,
  "useControlnet": false, "applyPulid": false, "fastMode": false
}
```

响应（同步，无轮询）：

```json
{"statusCode":200,"message":"success",
 "data":{"url":"https://static.aperogroup.ai/.../output/<ts>_0.jpeg","path":"..."},
 "timestamp":1793286133972}
```

实测：

| 场景 | 耗时 | 输出 |
|---|---|---|
| `{file}` 无风格无 prompt | 0.7 s（极小图） | 848×848 JPEG 55 KB |
| `{file, styleId=Ghibi, prompt}` | 8–14 s | 848×848 JPEG 44–147 KB（真实风格迁移：真人照 → 吉卜力动漫） |
| `{file, styleId=10009}`（RC 数字 ID） | 400 ERR16 | **RC 里的数字 style_id 不是本端点可用的 ID** |

> 坑：Glovy RC 的 `image_to_image_style` 用数字 `style_id`（100110/10009…），这类 ID 只用于 App 内埋点/展示；
> 服务端要求的是 style-manager 的 Mongo ObjectId。传数字时服务端报
> `Expect: length > 24, Value: 5, The provided style ID does not exist`。

### 4.2 文生图（`POST /api/v5/premium/text-2-image`）

```json
{"positivePrompt":"a cozy cabin in snowy forest, golden hour",
 "styleId":"64b260c21d50d66f545ea9f8",
 "negativePrompt":"blurry","width":768,"height":768,"seed":42}
```

实测：1024×1024 JPEG 225 KB，5.2–8.6 s（2 并发 p50 6.4 s）；`width/height` 建议 768 起；
不传 styleId 亦可（走默认模型）。

### 4.3 图生视频（`POST /api/v5/image-2-video`，video-gen-core）

```json
{"files":["video-compose/20261029/<uuid>/input.jpg"],
 "mode":"IMAGE_TO_VIDEO","keepFace":true,
 "positivePrompt":"the girl smiles gently, hair moves in the wind",
 "notificationProvider":"firebase","notificationId":"<32位随机hex>",
 "model":"inhouse","width":512,"height":512}
```

- **`notificationProvider` + `notificationId` 为必填**，缺任一 → 400 `client.bad-request`
- **`mode` 必须是小写 `"i2v"`**（不是枚举类里的 `IMAGE_TO_VIDEO`）——传大写枚举值一律
  `Not supported mode: IMAGE_TO_VIDEO of model: inhouse`。这条是踩坑点：APK 里的
  `p639z6/EnumC18481f`（IMAGE_TO_VIDEO 等）是另一套（Qwen editing）的枚举，**与视频端点无关**；
  视频端点接受的是 RC 风格配置里的 `style_mode`（`image_to_video_style.styles[].style_mode = "i2v"`）
- `model` 只接受 `inhouse` / `seedance-lite` / `seedance-pro`；`inhouse` 即可出片
- 创建返回 `data.videoId`；轮询 `GET /api/v5/image-2-video/video/{videoId}`，
  状态在 **`data.result.videoStatus`**（`processing` → `completed`），成品在 **`data.result.resultFile`**
- **实测产出**：`ai-core-video-lite/.../<ts>_0.mp4` → **h264 / 704×704 / 121 帧 / 5.04 s / 927 KB**，
  端到端 ~35 s（含上传）
- `keepFace: true` 保脸；`width/height` 512 起；prompt 用自然语言描述动作即可

### 4.4 风格库（免额外鉴权，但需同一套签名头）

- `GET https://api-style-manager.aperogroup.ai/v3/styles?page=N`（100/页，`totalPages=39`，`totalItems=3826`）
  返回 `_id / project / name / key(缩略图) / prompt / config{...}`
- `GET https://api-style-manager.aperogroup.ai/category` → 590 类目
  （`imageToImage` 219、`inspirations` 134、`aiFashion` 119、`avatar` 75、`textToImage` 17…）
- 54 个 project 命名空间：`Inhouse Default Configs` 486、`Artimind` 424、`AI_Realistic_Art_ANDROID` 248、
  `AI_Artrix_ANDROID` 176、`AI_Genius` 159 …

---

### 4.5 兄弟端点实测全表（2026-10-29，全部真实调用）

| 能力 | 端点（POST） | host | body | 实测 | 时延 |
|---|---|---|---|---|---|
| 画质增强 | `/api/v5/image-enhance` | wrapper | `{file}` | ✅ 201 | 5.2 / 9.1 s |
| 老照片修复 | `/api/v5/image-restore` | wrapper | `{file}` | ✅ 201 | 14.0 s |
| 扩图 | `/api/v5/image-outpainting` | wrapper | `{file, prompt, upScale, guidanceScale…}` | ✅ 201 | 8.9 s |
| 抠背景 | `/api/v5/remove-background` | wrapper | `{file}` | ✅ 201 | 3.0 s |
| 去物体 | `/api/v5/remove-object` | wrapper | `{file, mask}` | ✅ 201 | 16.2 s |
| 自然语言编辑 | `/api/v5.1/qwen-editing` | wrapper | `{files:[path], mode:"IMAGE_EDITING", positivePrompt, acceptNSFW}` | ✅ 201 | 9.6 s |
| 人像美颜 | `/api/v5/beauty` | beauty-core | `{file, ...}` | ✅ 201 | 2.9 s |
| AI 换装 | `/api/v5/clothes-changing` | cloth-change-core | `{file, prompt}` | ✅ 201 | 9.1 s |
| 服装试穿 | `/api/v5/fitting` | fitting-core | `{inputImage, clothImage, clothType}` | ✅ 201 | 5.4 s |
| 图像分割 | `/api/v5/segment` | segment-core | `{file}` | ✅ 201（`data:[]` 需按分割配置参数） | 2.8 s |
| 局部重绘 | `/api/v1/image-inpainting` | wrapper | **multipart**: `file` + `mask`(path) + `prompt` | ✅ 201 | 12.0 s |

**踩坑（都已实测确认）**

1. **presigned 上传链只有 wrapper 有路由**：在 `image-restore-core` / `core-outpaint` 上请求
   `/api/v5/image-restore/presigned-link` 一律 **404**；`BuildConfig` 里那堆 `URL_RESTORE` /
   `URL_EXPAND` / `URL_REMOVE_BG` 专用域名是**装饰性的**，真正的处理端点也都在 wrapper 上。
   → 传图统一走 `wrapper`，仅 beauty/cloth/fitting/segment/objectrm/video 的业务调用分发到专用 host。
2. `fitting` 字段名是 **`inputImage` / `clothImage` / `clothType`**，不是 `file`；
   `clothType ∈ {upper_body, lower_body, full_body}`（传 `upper` 会报枚举错误）。
3. `remove-object` 的 `mask` 是**另一个已上传的 path**，不是 base64、不是空串。
4. `inpainting` 要求 **multipart/form-data**（`RequestBody` 直传），JSON 会报 `Invalid content type`。
5. `segment` 返回 201 但 `data:[]`，需要按其分割档位参数（未深挖）。

---

## 5. 加固 / 混淆情况

| 项 | 结论 |
|---|---|
| DEX 加密 | 无（8 个 dex 明文，jadx 直出源码；448 处反编译警告均为 Kotlin 协程样板） |
| 字符串混淆 | 局部（`assets/dic` 4 KB 字典 + PGL armor lib），业务常量明文可见 |
| native | `libnativelib.so` / `libsigner.so` / `libpglarmor.so` / `libnms.so`（广告 SDK 与加固），**关键协议全在 Java/Kotlin** |
| 证书固定 | 无（`assets/prod.pem` 是业务 RSA 公钥，不是 pinning） |
| Play Integrity | 代码存在（`AperoIntegrity`，cloudProjectNumber=10 未配置），但服务端**不校验** `x-api-token` |
| mod 壳 | `libSignatureKiller.so`（ApkSignatureKillerEx），仅影响 Firebase cert 头，不影响上游鉴权 |

---

## 6. 商业化模型（来自 RC，供定价参考）

| 键 | 值 |
|---|---|
| `free_image_generation_limit_per_day` | 1 |
| `free_video_generation_limit_per_day` | 1 |
| `limit_gen_image_sub_per_day` | 100 |
| `limit_gen_video_sub_per_day` | 50 |
| `limit_image_generate` | 2 |
| `ads_per_image_generate` | 1（激励 ad 换额度） |
| `auto_free_generate` | true |

即：免费用户每日 1 张，看激励广告 +1，订阅用户 100 张/天。**上游没有账号体系**——
额度限制全在客户端（RC 下发），2API 层不需要伪造内购，只需转发。

---

## 7. 实测数据汇总

| 项目 | 结果 |
|---|---|
| 真实出图 | 图生图 6/6 成功（含风格迁移）；文生图 8/8 成功 |
| 兄弟端点 | 11/11 能力实测打通（enhance/restore/outpaint/remove-bg/remove-object/qwen-edit/beauty/clothes/fitting/segment/inpainting） |
| 图生视频 | ✅ 出片 h264 / 704×704 / 121 帧 / 5.04 s / 927 KB，端到端 ~35 s |
| 图生图延迟 | p50 8.0 s / p95 14.3 s（2 并发，848×848） |
| 文生图延迟 | p50 6.4 s / p95 8.6 s（2 并发，1024×1024） |
| 本地网关吞吐（mock） | 300 请求 / 30 并发：100% 成功，326 rps，p50 88.9 ms |
| 浏览器 e2e | PASS（首屏 → 风格库 → 选风格 → 上传 → 出图 848px → 统计刷新） |
| 上游健康 | `/health` `{"isHealth":true,"wrapper":{"limit":20}}` |

---

## 8. 风险与未验证项

1. **key 生命周期**：Glovy 自身 key 已被停用（ERR15），现依赖兄弟 App 的 key。厂商随时可停 → 网关已支持 `APERO_API_KEY` / `config.json` / `fetch_rc.py` 三条取 key 路径，后续应加 key 池轮换。
2. **合规**：上游是第三方生产服务，非自建额度。转发他人 App 的客户端 key 可能被厂商风控封禁；`/health` 显示 wrapper limit 20，不建议大规模并发。
3. **仍未深挖**：`segment` 返回空数组（需按分割档位参数）；`body beautify`（`/api/v4/beauty`）未单独实测；`art-premium-core` 的 premium 模型矩阵未遍历；Play Integrity 真实风控收紧后可能变为必需。
4. **输出尺寸**：图生图随输入（848×848），文生图 1024×1024，视频 704×704；`imageSize/fixWidth` 等参数对输出尺寸的影响未做 A/B。
